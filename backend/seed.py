"""生成示例题库：50 道题目，覆盖 5 种题型，供刷题侧开发使用。"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.auth import hash_password  # noqa: E402
from app.db import DB_PATH, init_db, new_id  # noqa: E402

BANK_NAME = "计算机基础 · 示例题库"

# 双方共用的联调账号：admin 为管理员，member 为普通用户，便于测权限分支
DEV_ACCOUNTS = [
    ("admin", "mojuan-dev", "开发管理员", 1),
    ("member", "mojuan-dev", "开发成员", 0),
]

SINGLE = [
    ("CPU 的中文全称是？", ["中央处理器", "图形处理器", "随机存储器", "输入输出设备"], 0, "CPU（Central Processing Unit）即中央处理器。", ["硬件"]),
    ("1KB 等于多少字节？", ["1000", "1024", "2048", "512"], 1, "存储单位按 2 的幂递进，1KB = 1024B。", ["基础"]),
    ("TCP/IP 参考模型分为几层？", ["3 层", "4 层", "5 层", "7 层"], 1, "TCP/IP 为四层，OSI 为七层。", ["网络"]),
    ("二进制 1010 转换为十进制是？", ["8", "9", "10", "12"], 2, "1×8+0×4+1×2+0×1 = 10。", ["基础"]),
    ("栈的访问特点是？", ["先进先出", "后进先出", "随机访问", "按优先级"], 1, "栈只允许在栈顶操作，是后进先出（LIFO）。", ["数据结构"]),
    ("HTTP 协议的默认端口是？", ["21", "22", "80", "443"], 2, "HTTP 默认 80，HTTPS 默认 443。", ["网络"]),
    ("平均时间复杂度为 O(n log n) 的排序算法是？", ["冒泡排序", "插入排序", "快速排序", "选择排序"], 2, "快速排序平均 O(n log n)，最坏退化为 O(n²)。", ["算法"]),
    ("IPv4 地址长度为多少位？", ["16 位", "32 位", "64 位", "128 位"], 1, "IPv4 为 32 位，IPv6 为 128 位。", ["网络"]),
    ("操作系统中 CPU 调度的基本单位是？", ["进程", "线程", "程序", "作业"], 1, "进程是资源分配单位，线程是调度单位。", ["操作系统"]),
    ("数据库中唯一标识一条记录的约束是？", ["外键", "主键", "索引", "默认值"], 1, "主键唯一标识记录且不可为空。", ["数据库"]),
    ("面向对象三大特性不包括？", ["封装", "继承", "多态", "并发"], 3, "三大特性为封装、继承、多态。", ["程序设计"]),
    ("HTTPS 协议的默认端口是？", ["80", "443", "8080", "22"], 1, "HTTPS 默认使用 443 端口。", ["网络"]),
    ("下列排序中稳定的是？", ["快速排序", "堆排序", "归并排序", "选择排序"], 2, "归并排序稳定；快排与堆排序不稳定。", ["算法"]),
    ("与数组相比，链表的主要优势是？", ["随机访问快", "插入删除效率高", "占用空间小", "缓存友好"], 1, "链表已知位置插入删除为 O(1)。", ["数据结构"]),
    ("DNS 的主要作用是？", ["分配 IP 地址", "将域名解析为 IP", "加密传输数据", "检测网络故障"], 1, "DNS 负责域名到 IP 的解析。", ["网络"]),
    ("递归算法必须具备的是？", ["循环变量", "终止条件", "全局变量", "异常处理"], 1, "没有终止条件会导致无限递归。", ["算法"]),
    ("十六进制 0x1F 转换为十进制是？", ["15", "31", "32", "63"], 1, "1×16+15 = 31。", ["基础"]),
    ("二叉树第 k 层（根为第 1 层）最多有多少个节点？", ["k", "2k", "2^(k-1)", "2^k"], 2, "第 k 层最多 2^(k-1) 个节点。", ["数据结构"]),
    ("Java 源代码编译后生成的是？", ["机器码", "字节码", "汇编代码", "中间文本"], 1, "Java 编译为字节码，由 JVM 执行。", ["程序设计"]),
    ("HTTP 状态码 500 表示？", ["请求成功", "未找到", "权限不足", "服务器内部错误"], 3, "5xx 表示服务器端错误。", ["网络"]),
]

MULTI = [
    ("下列属于面向对象三大特性的有？", ["封装", "继承", "多态", "递归"], [0, 1, 2], "三大特性为封装、继承、多态。", ["程序设计"]),
    ("产生死锁的必要条件包括？", ["互斥条件", "占有且等待", "不可抢占", "循环等待"], [0, 1, 2, 3], "四个条件同时满足才可能死锁。", ["操作系统"]),
    ("关于 TCP 协议，正确的有？", ["面向连接", "提供可靠传输", "面向字节流", "不保证顺序"], [0, 1, 2], "TCP 面向连接、可靠、按序。", ["网络"]),
    ("下列属于稳定排序的有？", ["冒泡排序", "插入排序", "归并排序", "快速排序"], [0, 1, 2], "冒泡、插入、归并是稳定的。", ["算法"]),
    ("常见的进程间通信方式包括？", ["管道", "消息队列", "共享内存", "信号量"], [0, 1, 2, 3], "此外还有信号、套接字等。", ["操作系统"]),
    ("下列属于 HTTP 请求方法的有？", ["GET", "POST", "PUT", "DELETE"], [0, 1, 2, 3], "对应查询、提交、更新、删除。", ["网络"]),
    ("下列属于线性结构的有？", ["数组", "栈", "队列", "链表"], [0, 1, 2, 3], "四者都是线性结构。", ["数据结构"]),
    ("下列操作平均时间复杂度为 O(1) 的有？", ["数组按下标访问", "哈希表平均查找", "数组查找指定值", "有序数组二分查找"], [0, 1], "数组随机访问与哈希表平均查找为 O(1)。", ["算法"]),
    ("数据库事务的 ACID 特性包括？", ["原子性", "一致性", "隔离性", "持久性"], [0, 1, 2, 3], "ACID 即这四项。", ["数据库"]),
    ("下列可能造成内存泄漏的做法有？", ["申请后未释放", "循环引用且无回收机制", "缓存无限增长", "使用局部变量"], [0, 1, 2], "局部变量随栈帧回收。", ["程序设计"]),
]

TRUE_FALSE = [
    ("栈是一种先进先出的数据结构。", False, "栈是后进先出，队列才是先进先出。", ["数据结构"]),
    ("二叉树中每个节点的度最多为 2。", True, "二叉树每个节点最多两个子节点。", ["数据结构"]),
    ("进程是操作系统进行资源分配的基本单位。", True, "进程是资源分配单位。", ["操作系统"]),
    ("HTTP 协议是无状态协议。", True, "HTTP 本身不保存状态。", ["网络"]),
    ("快速排序在最坏情况下时间复杂度为 O(n²)。", True, "划分极度不平衡时退化为 O(n²)。", ["算法"]),
    ("IPv6 地址长度为 64 位。", False, "IPv6 地址为 128 位。", ["网络"]),
    ("哈希表在极端冲突下查找可能退化为 O(n)。", True, "全部映射到同一桶时退化为链表遍历。", ["数据结构"]),
    ("递归实现的算法一定比循环实现效率更高。", False, "递归有调用与栈空间开销。", ["算法"]),
]

FILL = [
    ("1GB 等于 ____ MB。", ["1024"], [["1024"]], "存储单位按 1024 递进。", ["基础"]),
    ("TCP 三次握手中，第二次握手报文的标志位是 ____ 和 ____。", ["SYN", "ACK"], [["SYN", "syn"], ["ACK", "ack"]], "服务端回应 SYN+ACK。", ["网络"]),
    ("数据库中唯一标识记录的约束称为 ____。", ["主键"], [["主键", "主关键字", "primary key"]], "即 Primary Key。", ["数据库"]),
    ("二叉树遍历包括前序、中序、后序和 ____ 遍历。", ["层序"], [["层序", "层次"]], "层序遍历按层访问。", ["数据结构"]),
    ("操作系统中 CPU 调度的基本单位是 ____。", ["线程"], [["线程", "thread"]], "线程是调度基本单位。", ["操作系统"]),
    ("HTTP 状态码 404 表示请求的资源 ____。", ["未找到"], [["未找到", "不存在", "找不到"]], "404 Not Found。", ["网络"]),
    ("时间复杂度 O(____) 表示线性阶。", ["n"], [["n", "N"]], "线性阶即 O(n)。", ["算法"]),
]

SUBJECTIVE = [
    ("简述进程与线程的区别。", ["进程是资源分配的基本单位，线程是 CPU 调度的基本单位", "线程共享进程的地址空间与资源", "线程切换开销小于进程"], "应从调度与资源两个维度回答。", ["操作系统"]),
    ("说明 TCP 三次握手的过程。", ["客户端发送 SYN", "服务端回应 SYN+ACK", "客户端发送 ACK 确认"], "三次握手用于建立连接并同步序号。", ["网络"]),
    ("什么是死锁？列出产生死锁的必要条件。", ["多个进程因竞争资源而相互等待，无法推进", "互斥条件", "占有且等待", "不可抢占", "循环等待"], "四个条件缺一不可。", ["操作系统"]),
    ("简述快速排序的基本思想及其时间复杂度。", ["选取基准元素，将序列划分为两部分", "递归排序子序列", "平均 O(n log n)，最坏 O(n²)"], "核心是分治与划分。", ["算法"]),
    ("数据库索引的作用是什么？使用索引有什么代价？", ["加快查询速度", "占用额外存储空间", "降低写入与更新性能"], "索引是典型的以空间换时间。", ["数据库"]),
]


def _fingerprint(content: str) -> str:
    digest = 5381
    for char in "".join(content.split()).lower():
        digest = ((digest << 5) + digest + ord(char)) & 0xFFFFFFFF
    return format(digest, "x")


def _insert(conn: sqlite3.Connection, bank_id: str, row: tuple) -> None:
    (
        q_type,
        content,
        options,
        answer,
        acceptable,
        explanation,
        tags,
        difficulty,
    ) = row
    conn.execute(
        """INSERT INTO questions
           (id, bank_id, type, content, options, answer, acceptable_answers,
            explanation, tags, difficulty, source, confidence, fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id(),
            bank_id,
            q_type,
            content,
            json.dumps(options, ensure_ascii=False) if options else None,
            json.dumps(answer, ensure_ascii=False),
            json.dumps(acceptable, ensure_ascii=False) if acceptable else None,
            explanation,
            json.dumps(tags, ensure_ascii=False),
            difficulty,
            "seed",
            1.0,
            _fingerprint(content),
        ),
    )


def seed() -> None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    stale = [
        row["id"]
        for row in conn.execute("SELECT id FROM banks WHERE name = ?", (BANK_NAME,))
    ]
    for bank_id in stale:
        conn.execute("DELETE FROM banks WHERE id = ?", (bank_id,))

    bank_id = new_id()
    conn.execute(
        "INSERT INTO banks (id, name, platform, description, is_shared) VALUES (?, ?, ?, ?, 1)",
        (bank_id, BANK_NAME, "示例", "seed 生成的开发调试数据，可随时删除"),
    )

    rows = []
    for content, options, answer, explanation, tags in SINGLE:
        opts = [{"key": chr(65 + i), "text": text} for i, text in enumerate(options)]
        rows.append(
            ("single_choice", content, opts, [chr(65 + answer)], None, explanation, tags, 2)
        )
    for content, options, answer, explanation, tags in MULTI:
        opts = [{"key": chr(65 + i), "text": text} for i, text in enumerate(options)]
        rows.append(
            (
                "multiple_choice",
                content,
                opts,
                [chr(65 + i) for i in answer],
                None,
                explanation,
                tags,
                3,
            )
        )
    for content, answer, explanation, tags in TRUE_FALSE:
        opts = [{"key": "T", "text": "正确"}, {"key": "F", "text": "错误"}]
        rows.append(
            ("true_false", content, opts, ["T" if answer else "F"], None, explanation, tags, 1)
        )
    for content, answer, acceptable, explanation, tags in FILL:
        rows.append(("fill_blank", content, None, answer, acceptable, explanation, tags, 3))
    for content, answer, explanation, tags in SUBJECTIVE:
        rows.append(("subjective", content, None, answer, None, explanation, tags, 4))

    for row in rows:
        _insert(conn, bank_id, row)

    for username, password, display_name, is_admin in DEV_ACCOUNTS:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE users SET password_hash = ?, display_name = ?, is_admin = ? "
                "WHERE username = ?",
                (hash_password(password), display_name, is_admin, username),
            )
        else:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, display_name, is_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), username, hash_password(password), display_name, is_admin),
            )

    conn.commit()
    conn.close()

    print(f"已生成题库「{BANK_NAME}」，共 {len(rows)} 道题目")
    print(
        f"  单选 {len(SINGLE)} · 多选 {len(MULTI)} · 判断 {len(TRUE_FALSE)}"
        f" · 填空 {len(FILL)} · 主观 {len(SUBJECTIVE)}"
    )
    print(f"  联调账号：admin / mojuan-dev（管理员）· member / mojuan-dev（普通）")


if __name__ == "__main__":
    seed()
