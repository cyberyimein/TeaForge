# 第二阶段开发

## 目标

能够输出带逻辑流程图的C1,C0覆盖度报告,并且达到100%的覆盖度.

## 细节计划

1.实现一个流程图绘制CLI,这个CLI会读取参数里的流程图语言(Mermaid),程序会保存为.mmd文件,并在生成报告时转换成SVG格式的图片,并插入到报告里.

2.程序需要时间参数里的mermaid是否正确的验证代码.如果不正确,或者没有参数,会返回提示并给出正确的mermaid语法示例. 因为cli是给AI调用的,所以这个验证功能是为了让AI能正确的生成mermaid代码.

3.程序需要实现测试覆盖度分析的功能,这个功能会读取pytest的测试代码和被测试的代码,分析测试覆盖度,并生成一个报告.报告里会包含C1,C0的覆盖度数据,以及对应的逻辑流程图.

4.python的测试覆盖度分析可以使用coverage.py这个库来实现,当被测试环境里缺乏这个库时,程序需要返回提示,指导AI去安装这个库.

## 外观

和step1里的PCL报告一样,title区使用克莱因蓝,同样title右下角有
“Design by TeaForge.🍵”

页尾同样要有“Your AI agent generated this report using TeaForge. Now it’s tea time! 🍵”

风格可以参考pcl.html

## 数据结构设计
同样导出到output文件夹里,命名为文件名_coverage_report.html,文件里包含覆盖度数据和流程图的SVG图片.

mmd文件保存到output/files文件夹里,命名为文件名_coverage_report.mmd等

## API设计

生成流程图是CLI
调用报告生成是CLI
导出为PDF也是CLI
CLI需要help之类的设计
风格参考Step1.md