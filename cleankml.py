import os
import sys
import shutil
import datetime
from tqdm import tqdm

def sanitize_path(path):
    """
    将路径中的特殊字符替换为下划线，以匹配之前脚本生成的命名规则。
    """
    sanitized = path.replace(":", "").replace("\\", "_").replace("/", "_")
    sanitized = sanitized.replace(" ", "_")  # 替换空格
    return sanitized

def find_output_subdirs(main_dir):
    """
    遍历总目录，找到所有输出子目录。
    输出子目录包含至少一个 .kml 文件或一个 _log.txt 文件。
    """
    output_subdirs = []
    for root, dirs, files in os.walk(main_dir):
        # 跳过 Consolidated_Output 目录
        if os.path.basename(root) == "Consolidated_Output":
            continue

        # 检查当前目录是否包含至少一个 .kml 文件或一个 _log.txt 文件
        has_kml = any(file.lower().endswith('.kml') for file in files)
        has_log = any(file.lower().endswith('_log.txt') for file in files)

        if has_kml or has_log:
            output_subdirs.append(root)

    return output_subdirs

def delete_directories(directories, log_messages):
    """
    删除指定的目录及其内容。
    """
    for dir_path in tqdm(directories, desc="删除输出子目录", unit="个"):
        try:
            shutil.rmtree(dir_path)
            log_messages.append(f"已删除目录及其内容：{dir_path}")
            print(f"已删除目录及其内容：{dir_path}")
        except Exception as e:
            log_messages.append(f"无法删除目录：{dir_path}，错误：{e}")
            print(f"无法删除目录：{dir_path}，错误：{e}")

def delete_consolidated_output(main_dir, log_messages):
    """
    删除 Consolidated_Output 目录及其内容。
    """
    consolidated_folder = os.path.join(main_dir, "Consolidated_Output")
    if os.path.exists(consolidated_folder):
        try:
            shutil.rmtree(consolidated_folder)
            log_messages.append(f"已删除集中管理的输出文件夹：{consolidated_folder}")
            print(f"已删除集中管理的输出文件夹：{consolidated_folder}")
        except Exception as e:
            log_messages.append(f"无法删除集中管理的输出文件夹：{consolidated_folder}，错误：{e}")
            print(f"无法删除集中管理的输出文件夹：{consolidated_folder}，错误：{e}")
    else:
        log_messages.append(f"未找到集中管理的输出文件夹：{consolidated_folder}")
        print(f"未找到集中管理的输出文件夹：{consolidated_folder}")

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法: python delete_generated_files.py <总目录路径>")
        sys.exit(1)

    main_dir = sys.argv[1]
    if not os.path.isdir(main_dir):
        print(f"错误: 指定路径 '{main_dir}' 不是一个有效目录。")
        sys.exit(1)

    # 查找所有输出子目录
    print("正在查找所有输出子目录...")
    output_subdirs = find_output_subdirs(main_dir)
    print(f"共找到 {len(output_subdirs)} 个输出子目录。")

    # 查找 Consolidated_Output 文件夹
    consolidated_folder = os.path.join(main_dir, "Consolidated_Output")
    if os.path.exists(consolidated_folder):
        print(f"发现集中管理的输出文件夹：{consolidated_folder}")
    else:
        print("未找到集中管理的输出文件夹。")

    if not output_subdirs and not os.path.exists(consolidated_folder):
        print("未找到任何输出子目录或集中管理的输出文件夹需要删除。")
        sys.exit(0)

    # 列出所有将被删除的目录
    print("\n以下是将被删除的输出子目录：")
    for dir_path in output_subdirs:
        print(f" - {dir_path}")

    if os.path.exists(consolidated_folder):
        print(f"以下是将被删除的集中管理的输出文件夹：\n - {consolidated_folder}")

    # 请求用户确认
    confirm = input("\n是否确认删除上述所有文件和目录？[y/N]: ").strip().lower()
    if confirm != 'y':
        print("操作已取消。")
        sys.exit(0)

    # 初始化日志信息
    log_messages = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    log_filename = os.path.join(main_dir, f"deletion_log_{timestamp}.txt")

    # 删除输出子目录
    if output_subdirs:
        print("\n开始删除输出子目录...")
        delete_directories(output_subdirs, log_messages)
    else:
        print("\n未找到需要删除的输出子目录。")

    # 删除 Consolidated_Output 文件夹
    if os.path.exists(consolidated_folder):
        print("\n开始删除集中管理的输出文件夹...")
        delete_consolidated_output(main_dir, log_messages)
    else:
        print("\n无需删除集中管理的输出文件夹。")

    # 写入日志文件
    try:
        with open(log_filename, "w", encoding="utf-8") as log_f:
            log_f.write(f"删除操作日志 - {timestamp}\n\n")
            for message in log_messages:
                log_f.write(message + "\n")
        print(f"\n日志文件已保存为：{log_filename}")
    except Exception as e:
        print(f"\n无法写入日志文件：{log_filename}，错误：{e}")

    print("\n删除操作完成。")

if __name__ == "__main__":
    main()