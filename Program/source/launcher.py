"""Double-click launcher. Browser UI + FastAPI + SQLite, entirely offline."""
import argparse
import json
import logging
import os
from pathlib import Path
import socket
import sqlite3
import sys
import threading
import time
import webbrowser

import uvicorn
from backend.app import create_app
from backend.backup import backup_sqlite

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--data-dir')
    parser.add_argument('--self-test', action='store_true', help='Validate bundled desktop runtime without opening a browser')
    args = parser.parse_args()
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    location = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    data = Path(args.data_dir) if args.data_dir else location / 'data'
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data / 'flowdesk.log', encoding='utf-8', level=logging.INFO)
    # Portable data stays next to the exe, never in the temporary extraction folder.
    db_path = data / 'flowdesk.db'
    database_url = os.environ.get('FLOWDESK_DATABASE_URL', 'sqlite:///' + db_path.as_posix())
    app = create_app(database_url, base / 'frontend' / 'dist')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', args.port))
    port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, access_log=False))
    if args.headless:
        server.run(sockets=[sock])
        return
    import tkinter as tk
    from tkinter import messagebox, filedialog
    root = tk.Tk()
    if args.self_test:
        root.withdraw()
    root.title('FlowDesk · 账号与项目')
    root.geometry('500x370')
    root.resizable(False, False)
    root.configure(bg='#f5f7fc')
    tk.Label(root, text='FlowDesk', font=('Segoe UI', 26, 'bold'), bg='#f5f7fc', fg='#253052').pack(pady=(26, 4))
    tk.Label(root, text='Account + Project  /  v0.2.0', font=('Microsoft YaHei UI', 11), bg='#f5f7fc', fg='#667085').pack()
    status = tk.StringVar(value='正在启动…')
    tk.Label(root, textvariable=status, font=('Microsoft YaHei UI', 10), bg='#f5f7fc').pack(pady=18)
    tk.Button(root, text='打开 FlowDesk', font=('Microsoft YaHei UI', 11), bg='#5454df', fg='white', width=28, relief='flat', command=lambda: webbrowser.open(url)).pack(ipady=7)

    def backup():
        if not database_url.startswith('sqlite:///'):
            messagebox.showinfo('备份', '当前使用外部数据库，请用数据库管理工具备份。')
            return
        target = filedialog.asksaveasfilename(title='保存数据库备份', initialfile='FlowDesk-backup.db', defaultextension='.db', filetypes=[('SQLite 数据库', '*.db')])
        if target:
            if Path(target).resolve() == db_path.resolve():
                messagebox.showerror('无法保存', '请选择其他位置，不能覆盖正在使用的数据库。')
                return
            try:
                backup_sqlite(db_path, target)
                messagebox.showinfo('备份完成', '已保存此项目库的全部账号和项目。备份含所有用户数据，请妥善保管。恢复方法见使用说明。')
            except Exception as exc:
                messagebox.showerror('备份失败', str(exc))

    tk.Button(root, text='备份数据', command=backup, font=('Microsoft YaHei UI', 10), relief='flat', bg='#e8ebf4', width=31).pack(pady=10, ipady=4)
    tk.Label(root, text='关闭浏览器不会退出程序。\n关闭此窗口将停止服务；项目会保留。', font=('Microsoft YaHei UI', 9), bg='#f5f7fc', fg='#667085').pack(pady=4)
    worker = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    worker.start()
    deadline = time.monotonic() + 25
    def ready():
        if server.started:
            status.set('已运行 · ' + url)
            if args.self_test:
                root.update_idletasks()
                (data / 'runtime-check.json').write_text(json.dumps({'status': 'ok', 'desktop': 'Tk initialized', 'service': url, 'widgets': len(root.winfo_children())}), encoding='utf-8')
                root.after(100, close)
            else:
                webbrowser.open(url)
        elif not worker.is_alive() or time.monotonic() > deadline:
            status.set('启动失败，请查看 data/flowdesk.log')
        else:
            root.after(100, ready)
    def close():
        server.should_exit = True
        worker.join(timeout=4)
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, ready)
    root.mainloop()
    sock.close()
    app.state.engine.dispose()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.exception('FlowDesk startup failed')
        if '--headless' in sys.argv:
            raise
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk()
        window.withdraw()
        messagebox.showerror('FlowDesk 启动失败', f'{exc}\n\n请将程序放在可写文件夹后重新打开。')
        window.destroy()
