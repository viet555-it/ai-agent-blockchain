# Cài đặt và đóng gói từ source checkout

Ứng dụng đầy đủ được hỗ trợ theo cách chạy từ repository checkout với Python
3.12/Windows và dependency lock tại `requirements.txt`. Frontend, knowledge,
config, ABI/deployment và Alembic config được tìm theo repository root; model
cache/index/database được tạo riêng theo hướng dẫn README.

## Cài đặt

Sau khi tạo `.venv-phase3`, chạy tại root:

```powershell
.\.venv-phase3\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-phase3\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-phase3\Scripts\python.exe -m pip check
```

Lệnh editable chỉ đăng ký source packages, không cài lại dependency. Build tools
đã có trong lock. Dòng `-e .[dev]` được tách khỏi lock để file dependency không
phụ thuộc cwd; pytest/Ruff và các dependency dev vẫn được pin trong lock. Giữ
checkout tại đường dẫn đã đăng ký và chạy entry points bằng
`python -m backend.api.server`, `python -m scripts.<name>` như README. Sau khi
chuyển checkout hoặc cập nhật cấu hình package discovery, chạy lại lệnh editable.

`backend/requirements.txt` là entry point tương thích trỏ tới lock ở root, để
cách cài cũ không tiếp tục resolve một nhóm phiên bản Web3/API riêng. Đây là bộ
dependency đầy đủ cho ứng dụng, gồm RAG; không phải bản cài backend tối giản.
Khi dùng entry point này, vẫn chạy lệnh editable từ root sau khi cài dependencies.
Các dependency ranges ở `pyproject.toml` mô tả core; chúng không thay môi trường
ứng dụng đầy đủ đã khóa trong `requirements.txt`.

## Nội dung package

Package discovery bao gồm `agent`, `backend`, `config`, `eval`, `rag`, `scripts`,
`security`, `services`, `tools` và các subpackage có `__init__.py`. `backend` có
package initializer không mở tài nguyên. Test directories và namespace discovery
bị loại khỏi build; virtualenv/site-packages không được lấy vào package.

Code wheel chứa các module Python, YAML/JSON trong `config` và Alembic migration
Python files. Nó không phải bản triển khai độc lập của web app: frontend,
knowledge corpus, model/index, dữ liệu runtime và root deployment/config files
vẫn cần checkout. Chưa thiết kế installer/container hoặc wheel chứa mọi tài nguyên.

## Kiểm chứng offline

Trong môi trường đã cài lock, chạy:

```powershell
.\.venv-phase3\Scripts\python.exe -m scripts.check_packaging
```

Checker build code wheel từ source copy riêng, kiểm module/data bắt buộc và loại
trừ test/virtualenv; sau đó build editable artifact và thử 12 imports từ cwd khác
bằng tiến trình cô lập. Các finder editable cũ không được nạp vào smoke process.
Không cài/gỡ package trong môi trường đang dùng và không tải dependency từ mạng.

Build workspaces tạm nằm trong `.phase3/packaging/` và được dọn khi kết thúc; log
và `summary.json` được giữ tại đó. Checker xác minh import mapping và archive,
không chạy lifespan hoặc chứng minh cache/index/RPC đã sẵn sàng. Ma trận startup
và API được mô tả trong [runtime profiles](RUNTIME_PROFILES.md).
