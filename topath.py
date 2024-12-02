import os
import glob
from lxml import etree

# 定义命名空间
KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
XMP_NAMESPACE_GEOTAGGING = "http://www.w3.org/2003/01/geo/wgs84_pos#"
NSMAP_KML = {None: KML_NAMESPACE}
NSMAP_XMP = {
    'xmp': "http://ns.adobe.com/xap/1.0/",
    'exif': "http://www.w3.org/2003/04/exif/ns#",
    'geo': XMP_NAMESPACE_GEOTAGGING
}

def create_new_kml():
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
    # 定义Track样式
    style_track = etree.SubElement(document, "Style", id="track")
    line_style = etree.SubElement(style_track, "LineStyle")
    color = etree.SubElement(line_style, "color")
    color.text = "ff0000ff"  # 红色
    width = etree.SubElement(line_style, "width")
    width.text = "3"

def process_kml_file(file_path, folder_tracks):
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
                    # 可以稍微调整第二个点以确保轨迹存在
                    # 例如，增加0.000001度
                    lon2 = float(lon) + 0.000001
                    lat2 = float(lat) + 0.000001
                    coord_str = f"{lon},{lat},0 {lon2},{lat2},0"
                    coordinates_new.text = coord_str
    except Exception as e:
        print(f"处理 KML 文件时出错 ({file_path}): {e}")

def process_xmp_file(file_path, folder_tracks):
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
        # 可以稍微调整第二个点以确保轨迹存在
        lon2 = lon + 0.000001
        lat2 = lat + 0.000001
        coord_str = f"{lon},{lat},0 {lon2},{lat2},0"
        coordinates_new.text = coord_str

        print(f"已处理 XMP 文件: {file_path}")

    except Exception as e:
        print(f"处理 XMP 文件时出错 ({file_path}): {e}")

def main():
    # 创建新的 KML 结构
    new_kml, folder_tracks = create_new_kml()

    # 获取当前目录下所有 KML 文件和 XMP 文件
    kml_files = glob.glob("*.kml")
    xmp_files = glob.glob("*.xmp")

    if not kml_files and not xmp_files:
        print("当前目录下没有找到 KML 或 XMP 文件。")
        return

    # 处理 KML 文件
    for file in kml_files:
        print(f"正在处理 KML 文件: {file}")
        process_kml_file(file, folder_tracks)

    # 处理 XMP 文件
    for file in xmp_files:
        print(f"正在处理 XMP 文件: {file}")
        process_xmp_file(file, folder_tracks)

    # 保存新的 KML 文件
    output_file = "converted_tracks.kml"
    try:
        etree.ElementTree(new_kml).write(output_file, pretty_print=True, xml_declaration=True, encoding='UTF-8')
        print(f"转换完成。新文件已保存为: {output_file}")
    except Exception as e:
        print(f"保存 KML 文件时出错: {e}")

if __name__ == "__main__":
    main()