"""Transport mỏng gọi vào cùng một core (hợp đồng §1.3.2, Figure 1).

- http/  — đường chấm điểm: 2 endpoint §4.1, harness gọi theo từng lượt, mọi tuần.
- phone/ - provider-independent status adapter; no carrier connection yet.

Không đặt logic hội thoại ở đây: transport chỉ đổi request/response sang kiểu của engine.
"""
