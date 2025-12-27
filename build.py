from requests import get as iget
from zipfile import ZipFile
from os import remove, name, system, chdir as cd
from shutil import rmtree as rm, make_archive
IS_WINDOWS = True if name == 'nt' else False

url = 'https://www.pylindex.top/naga/files/build_files/py3119.zip'
response = iget(url)
with open("py3119.zip", "wb") as code:
    code.write(response.content)

f = ZipFile("py3119.zip", 'r')
for file in f.namelist():
    f.extract(file, ".")
f.close()

remove("py3119.zip")
rm(".venv")

if IS_WINDOWS:
    system(".\\py3119\\python.exe -m pip install --upgrade pip")
    system(".\\py3119\\python.exe -m pip install -r requirements.txt")
else:
    system("wine ./py3119/python.exe -m pip install --upgrade pip")
    system("wine ./py3119/python.exe -m pip install -r requirements.txt")

with open("使用必看说明.txt", "w", encoding="utf-8") as f:
    f.write("""双击 启动.cmd 即可运行
有问题请反馈至QQ：1708213363
config.json配置可参考README.md相关部分
使用需在config.json内填入api_key，可前往Deepseek申请一个（无账号请注册，并充值几元钱）：https://platform.deepseek.com
""")

with open("启动.cmd", "w", encoding="utf-8") as f:
    f.write("""@echo off
chcp 65001
set PATH=""
.\\py3119\\python.exe main.py
""")
    
cd("..")

make_archive(
    base_name='NagaAgent_Win64',
    format='zip',
    root_dir='./NagaAgent',
    base_dir='.',  # 只压缩my_project文件夹内的内容
    verbose=True            # 显示压缩过程
)
