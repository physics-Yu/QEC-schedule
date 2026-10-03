# d=3 逻辑组件理想协议

`logical_gadgets.py` 复用项目的9 data surface checks及 signed Pauli Clifford共轭。它不插入猜测的syndrome轮数，也不生成detectors、decoder、运输或资源时间。

`transversal_cnot('A', 'B')` 对两块同朝向patch的对应9个data执行有向CNOT。提供checks/logicals输入合同、精确logical operator输出images、backend layer请求和27门H(target)-CZ-H(target)物理耦合片段。输出patch定义保持。不同朝向显式拒绝，须另有经过验证的数据置换。

`logical_hadamard('A')` 提供9个物理H及standard↔dual输出合同：原X checks变为新Z checks，原Z checks变为新X checks，logical X/Z按H语义交换。边界类型交换，原子role坐标保留；这不是保持原朝向的完整H协议，不声称刚性AOD可旋转。后续syndrome及CNOT必须读取新朝向；恢复原朝向需要额外合法移动/置换协议。

`transversal_cz` 拒绝同朝向physical CZ等于logical CZ的快捷假设。H/CNOT/H构造涉及中间不同朝向及配对映射，首版未实现。

测试对两种朝向逐一验证所有16个双块稳定子生成元的共轭属于原group，及Xc→XcXt、Zt→ZcZt、Zc/Xt不变；H验证所有checks和logical映射。这里只验收理想codespace语义，未证明带噪容错或物理可执行。
