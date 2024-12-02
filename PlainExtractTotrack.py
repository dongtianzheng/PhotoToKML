#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
import math
import datetime
import glob
from exif import Image
from pykml.factory import KML_ElementMaker as KML
from lxml import etree
from tqdm import tqdm
import numpy as np
from sklearn.cluster import DBSCAN

# =======================
# 第一部分：扁平化目录结构
# =======================

def flatten_directory(directory="."):
    """
    扁平化指定目录结构，将所有文件移动到根目录，并删除空的子目录。
    """
    directory = os.path.abspath(directory)  # 获取绝对路径
    if not os.path.isdir(directory):
        print(f"{directory} 不是一个有效的目录。")
        return

    # 遍历目录树
    for root, dirs, files in os.walk(directory):
        # 跳过根目录本身
        if root == directory:
            continue

        for file in files:
            source_path = os.path.join(root, file)
            destination_path = os.path.join(directory, file)

            # 检查文件名冲突并解决
            if os.path.exists(destination_path):
                base, ext = os.path.splitext(file)
                counter = 1
                while os.path.exists(destination_path):
                    destination_path = os.path.join(directory, f"{base}_{counter}{ext}")
                    counter += 1

            # 移动文件
            shutil.move(source_path, destination_path)
            print(f"移动: {source_path} -> {destination_path}")

        # 删除空目录
        for dir in dirs:
            try:
                os.rmdir(os.path.join(root, dir))
                print(f"删除空目录: {os.path.join(root, dir)}")
            except OSError:
                pass

    # 最后再次删除所有空目录
    for root, dirs, _ in os.walk(directory, topdown=False):
        for dir in dirs:
            dir_path = os.path.join(root, dir)
            try:
                os.rmdir(dir_path)
                print(f"删除空目录: {dir_path}")
            except OSError:
                pass

# =======================================
# 第二部分：提取GPS信息并生成KML和日志
# =======================================

def sanitize_path(path):
    """
    将路径中的特殊字符替换为下划线，以用于文件名。
    """
    sanitized = path.replace(":", "").replace("\\", "_").replace("/", "_")
    sanitized = sanitized.replace(" ", "_")  # 替换空格
    return sanitized

def dms_to_decimal(dms, ref):
    """
    将度、分、秒格式的坐标转换为十进制度数。
    """
    degrees, minutes, seconds = dms
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in ['S', 'W']:
        decimal = -decimal
    return decimal

def extract_gps(photo_path):
    """
    从照片文件中提取GPS信息和拍摄时间。
    """
    with open(photo_path, 'rb') as f:
        try:
            img = Image(f)
            if (img.has_exif and
                img.gps_latitude and
                img.gps_longitude and
                img.gps_latitude_ref and
                img.gps_longitude_ref):
                lat = dms_to_decimal(img.gps_latitude, img.gps_latitude_ref)
                lon = dms_to_decimal(img.gps_longitude, img.gps_longitude_ref)
                # 提取拍摄时间
                if hasattr(img, 'datetime_original'):
                    timestamp = img.datetime_original
                elif hasattr(img, 'datetime'):
                    timestamp = img.datetime
                else:
                    timestamp = None
                return lat, lon, timestamp
        except Exception:
            pass
    return None

def cluster_points(photos_with_gps, max_distance=1.8):
    """
    使用DBSCAN算法对坐标进行聚类，确保每个类中任意两点之间的距离不超过max_distance公里。
    """
    if not photos_with_gps:
        return {}

    # 提取坐标用于聚类
    coords = [(lat, lon) for _, lat, lon, _ in photos_with_gps]
    coords_rad = np.radians(coords)  # 将坐标转换为弧度
    eps = max_distance / 6371  # 地球半径为6371公里，计算DBSCAN的epsilon

    clustering = DBSCAN(eps=eps, min_samples=1, algorithm='ball_tree', metric='haversine').fit(coords_rad)
    labels = clustering.labels_
    clusters = {}
    for label, (photo_name, lat, lon, timestamp) in zip(labels, photos_with_gps):
        clusters.setdefault(label, []).append((photo_name, lat, lon, timestamp))
    return clusters

def create_kml(cluster_points_list, output_file, cluster_number, total_clusters, folder_name):
    """
    生成KML文件。
    """
    # 设置KML文档的名称
    kml_name = f"{folder_name}（第{cluster_number}个子类/共{total_clusters}个子类）"

    # 创建KML文档
    placemarks = []
    for photo_name, lat, lon, timestamp in cluster_points_list:
        placemark_elements = [
            KML.name(photo_name),
            KML.Point(KML.coordinates(f"{lon},{lat}"))
        ]
        if timestamp:
            # 格式化时间戳为ISO 8601格式
            timestamp_formatted = timestamp.replace(':', '-', 2)
            timestamp_formatted = timestamp_formatted.replace(' ', 'T') + 'Z'
            placemark_elements.insert(1, KML.TimeStamp(KML.when(timestamp_formatted)))
        placemark = KML.Placemark(*placemark_elements)
        placemarks.append(placemark)

    kml_doc = KML.kml(
        KML.Document(
            KML.name(kml_name),
            KML.description("GPS locations from photos"),
            *placemarks
        )
    )

    # 保存KML文件
    with open(output_file, "wb") as f:
        f.write(etree.tostring(kml_doc, pretty_print=True, xml_declaration=True, encoding="UTF-8"))

def process_directory(input_path, consolidated_output, generated_files):
    """
    处理单个叶目录，将KML和日志文件保存到consolidated_output文件夹中。
    """
    # 获取相对于主目录的相对路径
    relative_path = os.path.relpath(input_path)
    absolute_path = os.path.abspath(input_path)
    time_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    # 构建命名前缀
    sanitized_absolute = sanitize_path(absolute_path)
    sanitized_relative = sanitize_path(relative_path)
    prefix = f"{sanitized_absolute}_{sanitized_relative}_{time_str}"

    # 不再在每个叶目录中创建子文件夹，而是将KML和日志文件直接保存在consolidated_output中
    # 检查是否已经存在输出文件，避免重复处理
    # 这里假设每个叶目录只会被处理一次，或根据需要添加逻辑
    # 获取目录下的所有文件
    all_files = os.listdir(input_path)
    photo_files = [file for file in all_files if file.lower().endswith(('.jpg', '.jpeg', '.png'))]

    # 如果没有照片文件，跳过该目录
    if not photo_files:
        print(f"目录 '{input_path}' 中没有照片文件，跳过。")
        return

    log_file = os.path.join(consolidated_output, f"{prefix}_log.txt")

    photos_with_gps = []
    no_gps_count = 0
    failed_count = 0

    log_messages = []
    log_messages.append(f"目录 '{input_path}' 下共 {len(all_files)} 个文件，其中 {len(photo_files)} 张照片。")

    folder_name = os.path.basename(input_path)

    for photo in tqdm(photo_files, desc=f"处理照片 ({relative_path})", unit="张"):
        try:
            photo_path = os.path.join(input_path, photo)
            gps_data = extract_gps(photo_path)
            if gps_data:
                lat, lon, timestamp = gps_data
                photos_with_gps.append((photo, lat, lon, timestamp))
            else:
                no_gps_count += 1
        except Exception as e:
            failed_count += 1
            log_messages.append(f"处理失败的照片：{photo}，错误：{e}")

    total_discarded_points = 0
    total_clusters = 0

    if photos_with_gps:
        # 对GPS点进行聚类
        clusters = cluster_points(photos_with_gps, max_distance=1.8)  # 修改为1.8公里
        valid_cluster_count = 0
        total_clusters = len([c for c in clusters.values() if len(c) > 3])

        for k, cluster_points_list in clusters.items():
            if len(cluster_points_list) > 3:
                valid_cluster_count += 1
                kml_filename = f"{prefix}_{valid_cluster_count}.kml"
                output_file = os.path.join(consolidated_output, kml_filename)
                create_kml(cluster_points_list, output_file, valid_cluster_count, total_clusters, folder_name)
                log_messages.append(f"生成了 KML 文件：{kml_filename}，包含 {len(cluster_points_list)} 个点。")
                
                # 记录生成的文件路径
                generated_files.append(output_file)
            else:
                total_discarded_points += len(cluster_points_list)

        log_messages.append(f"\n聚类结果：")
        log_messages.append(f"- 有效的类：{valid_cluster_count} 个")
        log_messages.append(f"- 被舍弃的类：{len(clusters) - valid_cluster_count} 个，舍弃的点数：{total_discarded_points} 个")
    else:
        log_messages.append("没有成功提取 GPS 信息的照片，未生成 KML 文件。")

    log_messages.append("\n处理结果：")
    log_messages.append(f"- 成功提取 GPS 信息的照片：{len(photos_with_gps)} 张")
    log_messages.append(f"- 没有 GPS 信息的照片：{no_gps_count} 张")
    log_messages.append(f"- 处理失败的照片：{failed_count} 张")

    # 将日志信息写入日志文件
    with open(log_file, "w", encoding="utf-8") as log_f:
        log_f.write("\n".join(log_messages))

    # 记录生成的日志文件路径
    generated_files.append(log_file)

    print(f"处理完成，日志文件已保存为 {log_file}")

def is_leaf_directory(path):
    """
    判断目录是否为叶子目录。
    - 如果目录没有子目录，则为叶子目录。
    - 如果目录有子目录，但这些子目录中没有包含图片文件的目录，则为叶子目录。
    """
    with os.scandir(path) as it:
        for entry in it:
            if entry.is_dir():
                subdir_files = os.listdir(entry.path)
                if any(file.lower().endswith(('.jpg', '.jpeg', '.png')) for file in subdir_files):
                    return False
    return True

def copy_generated_files(generated_files, consolidated_output):
    """
    （可选）将所有生成的KML和日志文件复制到集中管理的输出文件夹中，保持层级结构。
    此处由于我们已经将所有文件保存在consolidated_output中，不需要额外复制。
    """
    # 由于文件已直接保存到consolidated_output，无需额外复制
    pass

# ===========================================
# 第三部分：将点转换为轨迹（Track）
# ===========================================

# 定义命名空间
KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
XMP_NAMESPACE_GEOTAGGING = "http://www.w3.org/2003/01/geo/wgs84_pos#"
NSMAP_KML = {None: KML_NAMESPACE}
NSMAP_XMP = {
    'xmp': "http://ns.adobe.com/xap/1.0/",
    'exif': "http://www.w3.org/2003/04/exif/ns#",
    'geo': XMP_NAMESPACE_GEOTAGGING
}

def create_new_kml_for_tracks():
    """
    创建新的KML结构用于轨迹。
    """
    # 创建根元素
    kml = etree.Element("{%s}kml" % KML_NAMESPACE, nsmap=NSMAP_KML)
    document = etree.SubElement(kml, "Document")

    # 添加名称
    name = etree.SubElement(document, "name")
    name.text = "Converted Tracks"

    # 定义样式
    define_styles(document)

    # 创建文件夹用于轨迹
    folder_tracks = etree.SubElement(document, "Folder")
    folder_name = etree.SubElement(folder_tracks, "name")
    folder_name.text = "Tracks"

    return kml, folder_tracks

def define_styles(document):
    """
    定义轨迹样式。
    """
    # 定义Track样式
    style_track = etree.SubElement(document, "Style", id="track")
    line_style = etree.SubElement(style_track, "LineStyle")
    color = etree.SubElement(line_style, "color")
    color.text = "ff0000ff"  # 红色
    width = etree.SubElement(line_style, "width")
    width.text = "3"

def process_kml_file_for_tracks(file_path, folder_tracks):
    """
    处理KML文件，提取Placemark并转换为轨迹。
    """
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()

        # 查找所有Placemark
        placemarks = root.findall(".//{%s}Placemark" % KML_NAMESPACE)

        for placemark in placemarks:
            point = placemark.find(".//{%s}Point" % KML_NAMESPACE)
            if point is not None:
                coordinates = point.find("{%s}coordinates" % KML_NAMESPACE)
                if coordinates is not None:
                    coord_text = coordinates.text.strip()
                    lon, lat, *rest = coord_text.split(',')

                    # 创建新的Placemark作为Track
                    new_placemark = etree.SubElement(folder_tracks, "Placemark")

                    # 复制名称
                    name = placemark.find("{%s}name" % KML_NAMESPACE)
                    if name is not None:
                        new_name = etree.SubElement(new_placemark, "name")
                        new_name.text = name.text

                    # 复制时间戳作为描述（可选）
                    timestamp = placemark.find(".//{%s}TimeStamp/{%s}when" % (KML_NAMESPACE, KML_NAMESPACE))
                    if timestamp is not None:
                        description = etree.SubElement(new_placemark, "description")
                        description.text = timestamp.text

                    # 应用Track样式
                    style_url = etree.SubElement(new_placemark, "styleUrl")
                    style_url.text = "#track"

                    # 创建LineString
                    line_string = etree.SubElement(new_placemark, "LineString")
                    tessellate = etree.SubElement(line_string, "tessellate")
                    tessellate.text = "1"
                    altitude_mode = etree.SubElement(line_string, "altitudeMode")
                    altitude_mode.text = "clampedToGround"

                    # 创建极小长度的轨迹（使用相同点）
                    coordinates_new = etree.SubElement(line_string, "coordinates")
                    # 稍微调整第二个点以确保轨迹存在
                    lon2 = float(lon) + 0.000001
                    lat2 = float(lat) + 0.000001
                    coord_str = f"{lon},{lat},0 {lon2},{lat2},0"
                    coordinates_new.text = coord_str
    except Exception as e:
        print(f"处理 KML 文件时出错 ({file_path}): {e}")

def process_xmp_file_for_tracks(file_path, folder_tracks):
    """
    处理XMP文件，提取地理坐标并转换为轨迹。
    """
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()

        # 提取地理坐标
        lat = None
        lon = None

        # 尝试不同的路径以找到纬度和经度
        lat_elements = root.xpath("//geo:lat | //exif:GPSLatitude | //xmp:Latitude", namespaces=NSMAP_XMP)
        lon_elements = root.xpath("//geo:lon | //exif:GPSLongitude | //xmp:Longitude", namespaces=NSMAP_XMP)

        if lat_elements:
            lat = lat_elements[0].text
        if lon_elements:
            lon = lon_elements[0].text

        if lat is None or lon is None:
            print(f"XMP 文件中缺少地理坐标: {file_path}")
            return

        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            print(f"无效的坐标值在 XMP 文件中: {file_path}")
            return

        # 创建新的 Placemark 作为 Track
        new_placemark = etree.SubElement(folder_tracks, "Placemark")

        # 使用文件名作为名称
        name = etree.SubElement(new_placemark, "name")
        name.text = os.path.basename(file_path)

        # 添加描述（可选，可以添加更多 XMP 元数据）
        description = etree.SubElement(new_placemark, "description")
        description.text = f"从 XMP 文件提取的坐标"

        # 应用 Track 样式
        style_url = etree.SubElement(new_placemark, "styleUrl")
        style_url.text = "#track"

        # 创建 LineString
        line_string = etree.SubElement(new_placemark, "LineString")
        tessellate = etree.SubElement(line_string, "tessellate")
        tessellate.text = "1"
        altitude_mode = etree.SubElement(line_string, "altitudeMode")
        altitude_mode.text = "clampedToGround"

        # 创建极小长度的轨迹（使用相同点）
        coordinates_new = etree.SubElement(line_string, "coordinates")
        # 稍微调整第二个点以确保轨迹存在
        lon2 = lon + 0.000001
        lat2 = lat + 0.000001
        coord_str = f"{lon},{lat},0 {lon2},{lat2},0"
        coordinates_new.text = coord_str

        print(f"已处理 XMP 文件: {file_path}")

    except Exception as e:
        print(f"处理 XMP 文件时出错 ({file_path}): {e}")

def process_tracks(consolidated_output, original_dir_name):
    """
    处理所有生成的KML和XMP文件，将点转换为轨迹，并生成最终的Track文件。
    """
    # 创建新的KML结构
    new_kml, folder_tracks = create_new_kml_for_tracks()

    # 获取consolidated_output中的所有KML文件和XMP文件
    kml_files = glob.glob(os.path.join(consolidated_output, "*.kml"))
    xmp_files = glob.glob(os.path.join(consolidated_output, "*.xmp"))

    if not kml_files and not xmp_files:
        print("在输出文件夹中没有找到KML或XMP文件。")
        return

    # 处理KML文件
    for file in kml_files:
        print(f"正在处理 KML 文件: {file}")
        process_kml_file_for_tracks(file, folder_tracks)

    # 处理XMP文件
    for file in xmp_files:
        print(f"正在处理 XMP 文件: {file}")
        process_xmp_file_for_tracks(file, folder_tracks)

    # 生成最终的Track文件名
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    track_filename = f"{original_dir_name}_{timestamp}.kml"
    output_file = os.path.join(consolidated_output, track_filename)

    # 保存新的KML文件
    try:
        etree.ElementTree(new_kml).write(output_file, pretty_print=True, xml_declaration=True, encoding='UTF-8')
        print(f"转换完成。新轨迹文件已保存为: {output_file}")
    except Exception as e:
        print(f"保存KML文件时出错: {e}")

# ======================
# 主函数：整合所有部分
# ======================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="整合脚本：扁平化目录、提取GPS信息、生成轨迹。")
    parser.add_argument("directory", nargs="?", default=".", help="指定要处理的目录，默认为当前目录。")
    args = parser.parse_args()

    main_dir = os.path.abspath(args.directory)
    print(f"处理的主目录: {main_dir}")

    if not os.path.isdir(main_dir):
        print(f"错误: 指定路径 '{main_dir}' 不是一个有效目录。")
        sys.exit(1)

    # 第一步：扁平化目录结构
    print("\n=== 第一步：扁平化目录结构 ===")
    flatten_directory(main_dir)
    print("目录结构已扁平化。")

    # 第二步：提取GPS信息并生成KML和日志
    print("\n=== 第二步：提取GPS信息并生成KML和日志 ===")

    # 创建集中管理的输出文件夹路径
    consolidated_folder = os.path.join(main_dir, "Consolidated_Output")
    os.makedirs(consolidated_folder, exist_ok=True)
    print(f"集中管理的输出文件夹已创建或已存在：{consolidated_folder}")

    # 遍历目录，找到所有的叶子目录
    leaf_directories = []
    for root, dirs, files in os.walk(main_dir):
        # 跳过集中管理的输出文件夹
        if os.path.commonpath([os.path.abspath(root)]) == os.path.commonpath([os.path.abspath(consolidated_folder)]):
            continue

        if is_leaf_directory(root):
            leaf_directories.append(root)

    print(f"共找到 {len(leaf_directories)} 个叶子目录。")

    generated_files = []

    for leaf_dir in leaf_directories:
        print(f"\n正在处理目录：{leaf_dir}")
        process_directory(leaf_dir, consolidated_folder, generated_files)

    # （可选）集中管理的复制步骤
    if generated_files:
        print("\n所有生成的文件已保存在：")
        for file_path in generated_files:
            print(f" - {file_path}")
    else:
        print("\n没有生成任何KML或日志文件。")

    # 第三步：将点转换为轨迹
    print("\n=== 第三步：将点转换为轨迹 ===")
    original_dir_name = os.path.basename(main_dir.rstrip(os.sep))
    process_tracks(consolidated_folder, original_dir_name)

    print("\n所有任务执行完毕。")

if __name__ == "__main__":
    main()