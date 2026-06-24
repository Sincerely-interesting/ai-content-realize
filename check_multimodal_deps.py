"""
多模态打标系统依赖检查和安装助手
"""
import subprocess
import sys
import os

def check_python_version():
    """检查Python版本"""
    print("=" * 60)
    print("🐍 检查 Python 版本")
    print("=" * 60)
    
    version = sys.version_info
    print(f"当前版本: {version.major}.{version.minor}.{version.micro}")
    
    if version.major >= 3 and version.minor >= 7:
        print("✅ Python版本满足要求 (>= 3.7)")
        return True
    else:
        print("❌ Python版本过低，需要 >= 3.7")
        return False


def check_package(package_name, import_name=None):
    """检查Python包是否安装"""
    if import_name is None:
        import_name = package_name
    
    try:
        __import__(import_name)
        print(f"✅ {package_name} 已安装")
        return True
    except ImportError:
        print(f"❌ {package_name} 未安装")
        return False


def check_python_packages():
    """检查Python依赖包"""
    print("\n" + "=" * 60)
    print("📦 检查 Python 依赖包")
    print("=" * 60)
    
    packages = {
        'pandas': 'pandas',
        'openpyxl': 'openpyxl',
        'Pillow': 'PIL',
        'requests': 'requests',
        'python-dotenv': 'dotenv'
    }
    
    all_installed = True
    for pkg_name, import_name in packages.items():
        if not check_package(pkg_name, import_name):
            all_installed = False
    
    return all_installed


def check_ffmpeg():
    """检查FFmpeg是否安装"""
    print("\n" + "=" * 60)
    print("🎬 检查 FFmpeg")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        
        if result.returncode == 0:
            # 提取版本信息
            output = result.stdout.decode('utf-8', errors='ignore')
            first_line = output.split('\n')[0]
            print(f"✅ FFmpeg 已安装: {first_line}")
            return True
        else:
            print("❌ FFmpeg 未正确安装")
            return False
            
    except FileNotFoundError:
        print("❌ FFmpeg 未找到")
        print("\n💡 安装方法:")
        print("   Windows: choco install ffmpeg")
        print("   或访问: https://ffmpeg.org/download.html")
        return False
    except Exception as e:
        print(f"❌ 检查FFmpeg时出错: {e}")
        return False


def check_whisper():
    """检查Whisper是否安装"""
    print("\n" + "=" * 60)
    print("🎤 检查 Whisper 语音识别")
    print("=" * 60)
    
    # 检查本地Whisper
    try:
        import whisper
        print("✅ 本地 Whisper 已安装")
        
        # 检查模型
        model_path = os.path.expanduser("~/.cache/whisper")
        if os.path.exists(model_path):
            models = os.listdir(model_path)
            if models:
                print(f"   已下载模型: {', '.join(models)}")
            else:
                print("   ⚠️  未下载模型，首次使用时会自动下载")
        else:
            print("   首次使用时会自动下载模型 (~142MB)")
        
        return True
        
    except ImportError:
        print("❌ 本地 Whisper 未安装")
        print("\n💡 安装方法:")
        print("   pip install openai-whisper")
        print("   pip install torch torchvision torchaudio")
        return False


def check_env_file():
    """检查.env文件"""
    print("\n" + "=" * 60)
    print("🔧 检查环境配置 (.env)")
    print("=" * 60)
    
    if not os.path.exists('.env'):
        print("❌ .env 文件不存在")
        print("\n💡 创建方法:")
        print("   复制 .env.example 为 .env 并填写API Key")
        return False
    
    # 读取.env内容
    with open('.env', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查必需的Key
    checks = {
        'MIN_MAX_API_KEY': 'MiniMax API Key',
        'MODEL_NAME': '模型名称'
    }
    
    all_ok = True
    for key, desc in checks.items():
        if key in content:
            print(f"✅ {desc} 已配置")
        else:
            print(f"❌ {desc} 未配置")
            all_ok = False
    
    return all_ok


def install_packages():
    """安装缺失的Python包"""
    print("\n" + "=" * 60)
    print("📥 安装 Python 依赖包")
    print("=" * 60)
    
    packages = [
        'pandas',
        'openpyxl',
        'Pillow',
        'requests',
        'python-dotenv'
    ]
    
    for pkg in packages:
        print(f"\n正在安装 {pkg}...")
        try:
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', pkg],
                check=True
            )
            print(f"✅ {pkg} 安装成功")
        except subprocess.CalledProcessError as e:
            print(f"❌ {pkg} 安装失败: {e}")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🚀 MiniMax MCP 多模态打标系统 - 依赖检查")
    print("=" * 60)
    
    # 检查各项依赖
    results = {
        'Python版本': check_python_version(),
        'Python包': check_python_packages(),
        'FFmpeg': check_ffmpeg(),
        'Whisper': check_whisper(),
        '环境配置': check_env_file()
    }
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 依赖检查总结")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有依赖检查通过！可以运行打标脚本")
        print("\n使用方法:")
        print("  python minimax_mcp_multimodal_label_materials.py")
    else:
        print("⚠️  部分依赖未安装")
        print("\n请选择:")
        print("  1. 自动安装Python包")
        print("  2. 手动安装（查看上方提示）")
        print("  3. 退出")
        
        choice = input("\n请输入选项 (1/2/3): ").strip()
        
        if choice == '1':
            install_packages()
            print("\n✅ Python包安装完成，请手动安装FFmpeg和Whisper")
        elif choice == '2':
            print("\n💡 请参考上方提示手动安装")
        else:
            print("\n👋 退出")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
