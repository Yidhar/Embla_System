#清理打包产生的文件和文件夹
import os
import shutil
def clear_build_artifacts():
    # 删除解压的Python文件夹
    python_folder = "py3119"
    if os.path.exists(python_folder):
        shutil.rmtree(python_folder)
    
    # 删除使用说明文件
    usage_file = "使用必看说明.txt"
    if os.path.exists(usage_file):
        os.remove(usage_file)
    
    # 删除启动脚本
    startup_script = "启动.cmd"
    if os.path.exists(startup_script):
        os.remove(startup_script)
    
    print("清理完成，已删除打包产生的文件和文件夹。")
if __name__ == "__main__":
    clear_build_artifacts()