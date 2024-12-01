import os
import sys
import math
import datetime
import shutil
from exif import Image
from pykml.factory import KML_ElementMaker as KML
from lxml import etree
from tqdm import tqdm
import numpy as np
from sklearn.cluster import DBSCAN

def sanitize_path(path):
    """
    将绝对路径和相对路径中的特殊字符替换为下划线，以用于文件名。
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
    从照片文件中提取 GPS 信息和拍摄时间。
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
    使用 DBSCAN 算法对坐标进行聚类，确保每个类中任意两点之间的距离不超过 max_distance 公里。
    返回聚类结果，包含每个类中的照片名称、坐标和时间戳。
    """
    if not photos_with_gps:
        return {}

    # 提取坐标用于聚类
    coords = [(lat, lon) for _, lat, lon, _ in photos_with_gps]
    coords_rad = np.radians(coords)  # 将坐标转换为弧度
    eps = max_distance / 6371  # 地球半径为 6371 公里，计算 DBSCAN 的 epsilon

    clustering = DBSCAN(eps=eps, min_samples=1, algorithm='ball_tree', metric='haversine').fit(coords_rad)
    labels = clustering.labels_
    clusters = {}
    for label, (photo_name, lat, lon, timestamp) in zip(labels, photos_with_gps):
        clusters.setdefault(label, []).append((photo_name, lat, lon, timestamp))
    return clusters

def create_kml(cluster_points_list, output_file, cluster_number, total_clusters, folder_name):
    """
    生成 KML 文件。
    - cluster_points_list: list of tuples (photo_name, lat, lon, timestamp)
    - output_file: KML 文件路径
    - cluster_number: 当前类的编号
    - total_clusters: 类的总数
    - folder_name: 最低子目录的文件夹名
    """
    # 设置 KML 文档的名称
    kml_name = f"{folder_name}（第{cluster_number}个子类/共{total_clusters}个子类）"

    # 创建 KML 文档
    placemarks = []
    for photo_name, lat, lon, timestamp in cluster_points_list:
        placemark_elements = [
            KML.name(photo_name),
            KML.Point(KML.coordinates(f"{lon},{lat}"))
        ]
        if timestamp:
            # 格式化时间戳为 ISO 8601 格式
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

    # 保存 KML 文件
    with open(output_file, "wb") as f:
        f.write(etree.tostring(kml_doc, pretty_print=True, xml_declaration=True, encoding="UTF-8"))

def process_directory(input_path, main_dir, consolidated_output, generated_files):
    """
    处理单个叶目录。
    """
    # 获取相对于主目录的相对路径
    relative_path = os.path.relpath(input_path, main_dir)
    absolute_path = os.path.abspath(input_path)
    time_str = datetime.datetime.now().strftime("%Y%m%d%H%M")

    # 构建命名前缀
    sanitized_absolute = sanitize_path(absolute_path)
    sanitized_relative = sanitize_path(relative_path)
    prefix = f"{sanitized_absolute}_{sanitized_relative}_{time_str}"

    # 创建输出子目录的路径
    output_subdir = os.path.join(input_path, prefix)

    # 检查是否已经存在输出子目录，避免重复处理
    if os.path.exists(output_subdir):
        print(f"输出子目录已存在，跳过目录：{input_path}")
        return

    # 获取目录下的所有文件
    all_files = os.listdir(input_path)
    photo_files = [file for file in all_files if file.lower().endswith(('.jpg', '.jpeg', '.png'))]

    # 如果没有照片文件，跳过该目录
    if not photo_files:
        print(f"目录 '{input_path}' 中没有照片文件，跳过。")
        return

    # 创建输出子目录
    os.makedirs(output_subdir, exist_ok=True)

    log_file = os.path.join(output_subdir, f"{prefix}_log.txt")

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
        # 对 GPS 点进行聚类
        clusters = cluster_points(photos_with_gps, max_distance=1.8)  # 修改为1.8公里
        valid_cluster_count = 0
        total_clusters = len([c for c in clusters.values() if len(c) > 3])

        for k, cluster_points_list in clusters.items():
            if len(cluster_points_list) > 3:
                valid_cluster_count += 1
                kml_filename = f"{prefix}_{valid_cluster_count}.kml"
                output_file = os.path.join(output_subdir, kml_filename)
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

def is_leaf_directory(path, main_dir):
    """
    判断目录是否为叶子目录（根据新定义）。
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

def copy_generated_files(generated_files, main_dir, consolidated_output):
    """
    将所有生成的 KML 和日志文件复制到集中管理的输出文件夹中，保持层级结构。
    """
    for file_path in generated_files:
        relative_path = os.path.relpath(file_path, main_dir)
        target_path = os.path.join(consolidated_output, relative_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(file_path, target_path)
        print(f"已复制文件：{file_path} 到 {target_path}")

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python script.py <总目录路径>")
        sys.exit(1)

    main_dir = sys.argv[1]
    if not os.path.isdir(main_dir):
        print(f"错误: 指定路径 '{main_dir}' 不是一个有效目录。")
        sys.exit(1)

    # 判断是否需要创建集中管理的输出文件夹
    # 只有当总目录有子目录时才创建
    has_subdirectories = False
    for entry in os.scandir(main_dir):
        if entry.is_dir():
            has_subdirectories = True
            break

    # 创建集中管理的输出文件夹路径
    if has_subdirectories:
        consolidated_folder = os.path.join(main_dir, "Consolidated_Output")
        os.makedirs(consolidated_folder, exist_ok=True)
        print(f"集中管理的输出文件夹已创建：{consolidated_folder}")
    else:
        consolidated_folder = None
        print("指定的总目录本身是一个叶子目录，无需创建集中管理的输出文件夹。")

    # 遍历目录，找到所有的叶子目录
    leaf_directories = []
    for root, dirs, files in os.walk(main_dir):
        # 跳过集中管理的输出文件夹
        if consolidated_folder and os.path.commonpath([os.path.abspath(root)]) == os.path.commonpath([os.path.abspath(consolidated_folder)]):
            continue

        if is_leaf_directory(root, main_dir):
            leaf_directories.append(root)

    print(f"共找到 {len(leaf_directories)} 个叶子目录。")

    generated_files = []

    for leaf_dir in leaf_directories:
        print(f"\n正在处理目录：{leaf_dir}")
        process_directory(leaf_dir, main_dir, consolidated_folder, generated_files)

    # 集中管理的复制步骤
    if consolidated_folder and generated_files:
        print("\n开始集中管理所有生成的文件...")
        copy_generated_files(generated_files, main_dir, consolidated_folder)
        print(f"所有生成的文件已集中复制到：{consolidated_folder}")
    else:
        print("\n无需进行集中管理的复制步骤。")

    print("\n所有任务执行完毕。")

if __name__ == "__main__":
    main()