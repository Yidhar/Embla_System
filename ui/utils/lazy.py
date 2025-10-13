def lazy(func):
    """懒加载装饰器，用于全局变量"""
    class LazyWrapper:
        def __init__(self, func):
            self.func = func
            self.value = None
        
        def __getattr__(self, name):
            # 首次访问时执行初始化
            if self.value is None:
                self.value = self.func()
            # 支持像普通变量一样访问属性
            return getattr(self.value, name)
        
        def __repr__(self):
            # 打印时触发加载
            if self.value is None:
                self.value = self.func()
            return repr(self.value)
    
    return LazyWrapper(func)

"""使用案例
# 全局变量定义（用装饰器标记）
@lazy
def heavy_global_data():
    # 这里写初始化逻辑（耗时操作）
    print("首次访问，加载全局数据...")
    return [i*3 for i in range(1000000)]


# 直接像普通全局变量一样使用
print(heavy_global_data)  # 首次访问触发加载
print(heavy_global_data)  # 后续直接用缓存
print(len(heavy_global_data))  # 支持调用原对象方法/属性
"""