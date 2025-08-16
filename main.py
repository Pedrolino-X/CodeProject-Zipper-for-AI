import os
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Menu
import chardet
import threading
from pathlib import Path
import logging
import subprocess


LOG_DIR = Path.home() / ".projectdumper"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "dumper.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)


class ConfigManager:
    def __init__(self, app_name="ProjectDumper"):
        self.config_dir = LOG_DIR
        self.config_file = self.config_dir / "config.json"
        self.config_data = {}
        self.default_settings = {
            "ignored_dirs": ["__pycache__", ".git", ".idea", ".vscode", "node_modules", "dist", "build", "venv",
                             "target"],
            "ignored_exts": [".pyc", ".pyd", ".so", ".dll", ".exe", ".jpg", ".png", ".gif", ".zip", ".rar", ".pdf",
                             ".db", ".lock", ".log"],
            "max_size_mb": 5,
            "include_full_tree": True,
            "checked_paths": []
        }
        self._ensure_config_exists()
        self.load_config()

    def _ensure_config_exists(self):
        self.config_dir.mkdir(exist_ok=True)
        if not self.config_file.exists(): self.save_config()

    def load_config(self):
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logging.warning(f"Could not load config file: {e}. Starting with empty config.")
            self.config_data = {"projects": {}, "last_used_project": ""}

    def save_config(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
        except Exception:
            logging.error("Failed to save config file.", exc_info=True)

    def get_project_settings(self, project_path):
        project_path_str = str(Path(project_path).resolve())
        project_settings = self.default_settings.copy()
        if project_settings_saved := self.config_data.get("projects", {}).get(project_path_str):
            project_settings.update(project_settings_saved)
        return project_settings

    def save_project_settings(self, project_path, settings):
        if not project_path: return
        project_path_str = str(Path(project_path).resolve())
        if "projects" not in self.config_data: self.config_data["projects"] = {}
        self.config_data["projects"][project_path_str] = settings
        self.config_data["last_used_project"] = project_path_str
        self.save_config()

    def reset_project_to_default(self, project_path):
        if not project_path: return False
        project_path_str = str(Path(project_path).resolve())
        if self.config_data.get("projects", {}).pop(project_path_str, None):
            self.save_config()
            return True
        return False

    def clear_all_configs(self):
        self.config_data = {"projects": {}, "last_used_project": ""}
        self.save_config()


class EditableListbox:
    def __init__(self, parent, title, initial_items=None, on_change_callback=None):
        self.frame = ttk.Labelframe(parent, text=title)
        self.initial_items = initial_items or []
        self.on_change_callback = on_change_callback
        self.create_widgets()

    def create_widgets(self):
        self.tree = ttk.Treeview(self.frame, columns=("actions",), show="tree", height=6)
        self.tree.column("#0", width=200, minwidth=150)
        self.tree.column("actions", width=90, minwidth=70, anchor="center")
        self.tree.heading("#0", text="项目", anchor="w")
        self.tree.heading("actions", text="操作", anchor="center")
        self.tree.bind("<Double-1>", self.on_edit)
        self.tree.bind("<Button-1>", self.on_click)
        input_frame = ttk.Frame(self.frame)
        input_frame.pack(fill=tk.X, padx=5, pady=5)
        self.entry = ttk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.entry.bind("<Return>", lambda e: self.add_item())
        ttk.Button(input_frame, text="添加", command=self.add_item).pack(side=tk.RIGHT)
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.set_items(self.initial_items)
        self.edit_item = None

    def set_items(self, items):
        for i in self.tree.get_children(): self.tree.delete(i)
        for item in items: self.add_item_to_tree(item)

    def add_item_to_tree(self, text):
        return self.tree.insert("", "end", text=text, values=("✏️ 🗑️",))

    def add_item(self):
        text = self.entry.get().strip()
        if text and text not in self.get_all_items():
            self.add_item_to_tree(text)
            self.entry.delete(0, tk.END)
            if self.on_change_callback: self.on_change_callback()

    def on_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item: return
        column = self.tree.identify_column(event.x)
        if column == "#1":
            bbox = self.tree.bbox(item, "actions")
            if not bbox: return
            x_in_column = event.x - bbox[0]
            if x_in_column < bbox[2] / 2:
                self.start_edit(item)
            else:
                self.delete_item(item)

    def on_edit(self, event):
        item = self.tree.identify_row(event.y)
        if item and self.tree.identify_column(event.x) == "#0": self.start_edit(item)

    def start_edit(self, item):
        if self.edit_item: self.finish_edit()
        self.edit_item = item
        current_text = self.tree.item(item, "text")
        bbox = self.tree.bbox(item, "#0")
        if bbox:
            x, y, width, height = bbox
            self.edit_entry = tk.Entry(self.tree, borderwidth=0, highlightthickness=1)
            self.edit_entry.place(x=x, y=y, width=width, height=height)
            self.edit_entry.insert(0, current_text)
            self.edit_entry.select_range(0, tk.END)
            self.edit_entry.focus()
            self.edit_entry.bind("<Return>", self.finish_edit)
            self.edit_entry.bind("<Escape>", self.cancel_edit)
            self.edit_entry.bind("<FocusOut>", self.finish_edit)

    def finish_edit(self, event=None):
        if not self.edit_item or not hasattr(self, 'edit_entry'): return
        new_text = self.edit_entry.get().strip()
        if new_text and new_text not in [self.tree.item(i, "text") for i in self.tree.get_children() if
                                         i != self.edit_item]:
            self.tree.item(self.edit_item, text=new_text)
            if self.on_change_callback: self.on_change_callback()
        self.cleanup_edit()

    def cancel_edit(self, event=None):
        self.cleanup_edit()

    def cleanup_edit(self):
        if hasattr(self, 'edit_entry'):
            self.edit_entry.destroy()
            del self.edit_entry
        self.edit_item = None

    def delete_item(self, item):
        if messagebox.askyesno("确认删除", f"确定要删除 '{self.tree.item(item, 'text')}' 吗？"):
            self.tree.delete(item)
            if self.on_change_callback: self.on_change_callback()

    def get_all_items(self):
        return [self.tree.item(item, "text") for item in self.tree.get_children()]

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)


class ProjectDumperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.title("代码工程内容提取器")
        self.minsize(850, 650)
        self.source_dir = ""
        self.output_file = ""
        self.path_to_id_map = {}
        self.create_main_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_exit)
        try:
            self._load_last_used_project()
        except Exception:
            logging.error("Failed to load last project during startup.", exc_info=True)
            messagebox.showwarning("启动警告", "无法加载上一次的项目状态，可能是配置文件损坏或路径已更改。")

    def create_main_layout(self):
        main_container = ttk.Frame(self)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        main_paned_window = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        main_paned_window.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_paned_window, width=500)
        self._create_tree_view(left_frame)
        main_paned_window.add(left_frame, weight=3)
        right_frame = ttk.Frame(main_paned_window, width=300)
        self._create_control_panel(right_frame)
        main_paned_window.add(right_frame, weight=1)
        bottom_container = ttk.Frame(self)
        bottom_container.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=(5, 10))
        ttk.Separator(bottom_container, orient='horizontal').pack(fill=tk.X, pady=(0, 10))
        self._create_bottom_bar(bottom_container)

    def _create_tree_view(self, parent):
        tree_frame_container = ttk.Frame(parent)
        tree_frame_container.pack(fill=tk.BOTH, expand=True)
        tree_top_bar = ttk.Frame(tree_frame_container)
        tree_top_bar.pack(fill=tk.X)
        self.tree_label = ttk.Label(tree_top_bar, text="文件结构 (单击复选框切换状态)")
        self.tree_label.pack(side=tk.LEFT, padx=(5, 0))
        ttk.Button(tree_top_bar, text="🔄 刷新", command=self._refresh_tree_view).pack(side=tk.RIGHT)
        tree_frame = ttk.Frame(tree_frame_container)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("fullpath", "state"), show="tree")
        self.tree.column("#0", width=350, minwidth=200, stretch=tk.YES)
        self.tree.column("fullpath", width=0, stretch=tk.NO)
        self.tree.column("state", width=0, stretch=tk.NO)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-1>", self.on_single_click)
        ysb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.insert("", "end", iid="placeholder", text="请先选择一个源目录...")

    def _create_control_panel(self, parent):
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill=tk.BOTH, expand=True, padx=(10, 0))
        self.ignored_dirs_list = EditableListbox(control_frame, "忽略的目录名",
                                                 on_change_callback=self._save_settings_for_current_project)
        self.ignored_dirs_list.pack(fill=tk.X, pady=(0, 5))
        self.ignored_exts_list = EditableListbox(control_frame, "忽略的文件后缀",
                                                 on_change_callback=self._save_settings_for_current_project)
        self.ignored_exts_list.pack(fill=tk.X, pady=5)
        size_frame = ttk.Labelframe(control_frame, text="单个文件大小限制 (MB)")
        size_frame.pack(fill=tk.X, pady=5)
        self.max_size_var = tk.StringVar()
        self.max_size_entry = ttk.Entry(size_frame, textvariable=self.max_size_var, width=10)
        self.max_size_entry.pack(side=tk.LEFT, padx=5, pady=5)
        self.max_size_entry.bind("<FocusOut>", lambda e: self._save_settings_for_current_project())
        options_frame = ttk.Labelframe(control_frame, text="高级选项")
        options_frame.pack(fill=tk.X, pady=5, expand=False)
        self.include_full_tree_var = tk.BooleanVar()
        ttk.Checkbutton(options_frame, text="在开头包含完整项目结构树", variable=self.include_full_tree_var,
                        command=self._save_settings_for_current_project).pack(anchor="w", padx=5)

    def _create_bottom_bar(self, parent):
        path_frame = ttk.Frame(parent)
        path_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(path_frame, text="选择源目录...", command=self.select_source_directory).pack(side=tk.LEFT,
                                                                                                padx=(0, 5))
        self.source_label = ttk.Label(path_frame, text="源目录: 未选择", relief="sunken", anchor="w")
        self.source_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        output_frame = ttk.Frame(parent)
        output_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(output_frame, text="设置输出文件...", command=self.select_output_file).pack(side=tk.LEFT,
                                                                                               padx=(0, 5))
        self.output_label = ttk.Label(output_frame, text="输出到: 未设置", relief="sunken", anchor="w")
        self.output_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        action_frame = ttk.Frame(parent)
        action_frame.pack(fill=tk.X)
        self.generate_button = ttk.Button(action_frame, text="🚀 生成聚合文件", command=self.start_generation_thread)
        self.generate_button.pack(side=tk.LEFT, padx=(0, 10))
        self.config_button = ttk.Button(action_frame, text="⚙️ 配置")
        self.config_button.pack(side=tk.LEFT)
        self.config_menu = Menu(self, tearoff=0)
        self.config_menu.add_command(label="恢复当前项目为默认配置", command=self._reset_current_project_config)
        self.config_menu.add_command(label="清除所有已记忆的配置", command=self._clear_all_configs)
        self.config_menu.add_separator()
        self.config_menu.add_command(label="打开日志文件", command=self._open_log_file)
        self.config_button.bind("<Button-1>", self.show_config_menu)
        self.status_label = ttk.Label(action_frame, text="状态: 准备就绪")
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

    def show_config_menu(self, event):
        try:
            self.config_menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _open_log_file(self):
        try:
            os.startfile(LOG_FILE)
        except Exception:
            logging.error("Failed to open log file.", exc_info=True)
            messagebox.showerror("错误", f"无法打开日志文件，请手动访问:\n{LOG_FILE}")

    def _reveal_in_explorer(self, file_path):
        try:
            subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
        except (subprocess.CalledProcessError, FileNotFoundError):
            logging.error("Failed to reveal file in explorer.", exc_info=True)
            try:
                os.startfile(os.path.dirname(file_path))
            except Exception:
                messagebox.showerror("错误", f"无法在资源管理器中显示文件，请手动访问:\n{os.path.dirname(file_path)}")

    def _is_path_ignored(self, path):
        path_lower = path.lower()
        ignored_dirs = {d.lower() for d in self.ignored_dirs_list.get_all_items()}
        ignored_exts = {e.lower() for e in self.ignored_exts_list.get_all_items()}

        if any(part in ignored_dirs for part in Path(path_lower).parts):
            return True

        if os.path.splitext(path_lower)[1] in ignored_exts:
            return True

        return False

    def _load_last_used_project(self):
        last_project = self.config_manager.config_data.get("last_used_project")
        if last_project and Path(last_project).exists(): self._set_source_directory(last_project)

    def _load_settings_for_current_project(self):
        if not self.source_dir: return {}
        settings = self.config_manager.get_project_settings(self.source_dir)
        self.ignored_dirs_list.set_items(settings['ignored_dirs'])
        self.ignored_exts_list.set_items(settings['ignored_exts'])
        self.max_size_var.set(str(settings['max_size_mb']))
        self.include_full_tree_var.set(settings['include_full_tree'])
        return settings

    def _save_settings_for_current_project(self):
        if not self.source_dir: return
        checked_paths = [str(Path(path).resolve()) for path, iid in self.path_to_id_map.items() if
                         self.tree.exists(iid) and self.tree.set(iid, "state") != "unchecked"]
        try:
            max_size_val = float(self.max_size_var.get())
        except ValueError:
            max_size_val = 5.0
        settings = {"ignored_dirs": self.ignored_dirs_list.get_all_items(),
                    "ignored_exts": self.ignored_exts_list.get_all_items(), "max_size_mb": max_size_val,
                    "include_full_tree": self.include_full_tree_var.get(), "checked_paths": checked_paths}
        self.config_manager.save_project_settings(self.source_dir, settings)

    def _reset_current_project_config(self):
        if not self.source_dir: messagebox.showinfo("信息", "请先选择一个项目目录。"); return
        if messagebox.askyesno("确认", "确定要将当前项目的配置恢复为默认设置吗？"):
            if self.config_manager.reset_project_to_default(self.source_dir):
                self._load_settings_for_current_project();
                messagebox.showinfo("成功", "当前项目配置已恢复为默认。")
            else:
                messagebox.showinfo("信息", "当前项目没有已保存的自定义配置。")

    def _clear_all_configs(self):
        if messagebox.askyesno("确认", "警告：这将清除所有已保存的项目配置。\n确定要继续吗？"):
            self.config_manager.clear_all_configs();
            self._load_settings_for_current_project();
            messagebox.showinfo("成功", "所有已记忆的配置均已清除。")

    def _on_exit(self):
        self._save_settings_for_current_project(); self.destroy()

    def select_source_directory(self):
        path = filedialog.askdirectory(title="请选择代码工程根目录")
        if path: self._set_source_directory(path)

    def _set_source_directory(self, path):
        self.source_dir = os.path.normpath(path)
        self.source_label.config(text=f"源目录: {self.source_dir}")
        project_name = os.path.basename(self.source_dir)
        self.output_file = os.path.normpath(os.path.join(self.source_dir, f"{project_name}_dump.txt"))
        self.output_label.config(text=f"输出到: {self.output_file}")
        self.status_label.config(text="状态: 正在加载目录...")
        self.update()
        settings = self._load_settings_for_current_project()
        self.populate_tree(settings.get('checked_paths', []))
        self.status_label.config(text="状态: 准备就绪")

    def select_output_file(self):
        path = filedialog.asksaveasfilename(title="选择输出文件", initialfile=os.path.basename(
            self.output_file) if self.output_file else "project_dump.txt", initialdir=os.path.dirname(
            self.output_file) if self.output_file else os.getcwd(), defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path: self.output_file = os.path.normpath(path); self.output_label.config(text=f"输出到: {self.output_file}")

    def _refresh_tree_view(self):
        if not self.source_dir: return
        self._save_settings_for_current_project();
        self.status_label.config(text="状态: 正在刷新目录...");
        self.update()
        settings = self._load_settings_for_current_project();
        self.populate_tree(settings.get('checked_paths', []));
        self.status_label.config(text="状态: 准备就绪")

    def populate_tree(self, checked_paths=None):
        for i in self.tree.get_children(): self.tree.delete(i)
        self.path_to_id_map.clear()
        checked_paths_resolved = {str(Path(p).resolve()) for p in (checked_paths or [])}
        if not self.source_dir:
            self.tree.insert("", "end", iid="placeholder", text="请先选择一个源目录...")
            return
        root_path = self.source_dir
        root_id = self._add_node_to_tree("", root_path, is_root=True, iid="root", checked_paths=checked_paths_resolved)
        self.tree.item(root_id, open=True)
        try:
            for item in sorted(os.listdir(root_path)):
                self._add_node_to_tree(root_id, os.path.join(root_path, item), checked_paths=checked_paths_resolved)
        except OSError as e:
            logging.warning(f"Could not access {root_path}: {e}")
            self.tree.insert(root_id, "end", text=f"无法访问: {e.strerror}")
        if children := self.tree.get_children(root_id):
            self._update_parent_state(children[-1])

    def _add_node_to_tree(self, parent_id, path, is_root=False, iid=None, checked_paths=None):
        path = os.path.normpath(path)
        name = os.path.basename(path) if not is_root else (os.path.basename(path) or path)
        is_dir = os.path.isdir(path)
        state = "checked" if str(Path(path).resolve()) in checked_paths else "unchecked"
        text = self.format_tree_text(name, path, state)
        item_id = self.tree.insert(parent_id, "end", text=text, values=[path, state], iid=iid)
        self.path_to_id_map[path] = item_id
        if is_dir and not is_root:
            try:
                if os.listdir(path):
                    self.tree.insert(item_id, "end", text="loading...")
            except OSError:
                pass
        return item_id

    def get_checkbox_symbol(self, state):
        return {"unchecked": "☐", "checked": "☑", "tristate": "▣"}.get(state, "☐")

    def get_item_icon(self, path):
        return "📁" if os.path.isdir(path) else "📄"

    def format_tree_text(self, name, path, state):
        return f"{self.get_checkbox_symbol(state)} {self.get_item_icon(path)} {name}"

    def on_double_click(self, event):
        pass

    def on_tree_open(self, event):
        item_id = self.tree.focus()
        if not item_id or not self.tree.exists(item_id): return
        children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0])['text'] == "loading...":
            self.tree.delete(children[0])
            path = self.tree.set(item_id, "fullpath")
            parent_state = self.tree.set(item_id, "state")
            settings = self.config_manager.get_project_settings(self.source_dir)
            checked_paths_resolved = {str(Path(p).resolve()) for p in settings.get('checked_paths', [])}
            try:
                for item_name in sorted(os.listdir(path)):
                    full_path = os.path.join(path, item_name)
                    self._add_node_to_tree(item_id, full_path, checked_paths=checked_paths_resolved)
                if parent_state != "unchecked": self._update_children_state(item_id, parent_state)
            except OSError as e:
                logging.warning(f"Could not access {path}: {e}")
                self.tree.insert(item_id, "end", text=f"无法访问: {e.strerror}")

    def on_single_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id: return
        element = self.tree.identify_element(event.x, event.y)
        if element == 'tree': return
        bbox = self.tree.bbox(item_id, column="#0")
        if not bbox: return
        checkbox_start_x = bbox[0] + 20;
        checkbox_end_x = checkbox_start_x + 20
        if checkbox_start_x <= event.x < checkbox_end_x:
            current_state = self.tree.set(item_id, "state");
            new_state = "unchecked" if current_state == "checked" else "checked"
            self.toggle_check(item_id, new_state);
            self._save_settings_for_current_project()

    def toggle_check(self, item_id, state, propagate=True):
        if not self.tree.exists(item_id): return
        self.tree.set(item_id, "state", state)
        path = self.tree.set(item_id, "fullpath")
        name = os.path.basename(path) if self.tree.parent(item_id) else (
                    os.path.basename(self.source_dir) or self.source_dir)
        self.tree.item(item_id, text=self.format_tree_text(name, path, state))
        if propagate: self._update_children_state(item_id, state); self._update_parent_state(item_id)

    def _update_children_state(self, item_id, state):
        for child_id in self.tree.get_children(item_id):
            if self.tree.item(child_id)['text'] == "loading...": continue
            self.toggle_check(child_id, state, propagate=True)

    def _update_parent_state(self, item_id):
        parent_id = self.tree.parent(item_id)
        if not parent_id: return
        children = self.tree.get_children(parent_id)
        if not children: return
        child_states = {self.tree.set(child_id, "state") for child_id in children if
                        self.tree.item(child_id)['text'] != "loading..."}
        if len(child_states) == 1:
            parent_state = child_states.pop()
        else:
            parent_state = "tristate"
        self.tree.set(parent_id, "state", parent_state)
        path = self.tree.set(parent_id, "fullpath")
        name = os.path.basename(path) if self.tree.parent(parent_id) else (
                    os.path.basename(self.source_dir) or self.source_dir)
        self.tree.item(parent_id, text=self.format_tree_text(name, path, parent_state))
        self._update_parent_state(parent_id)

    def start_generation_thread(self):
        if not self.source_dir: messagebox.showwarning("警告", "请先选择一个源目录！"); return
        self._save_settings_for_current_project();
        self.generate_button.config(state="disabled");
        self.status_label.config(text="状态: 开始处理...");
        threading.Thread(target=self.process_files, daemon=True).start()

    def update_status(self, message):
        self.status_label.config(text=f"状态: {message}")

    def _is_path_selected(self, file_path):
        current_path = os.path.normpath(file_path)
        while True:
            if current_path in self.path_to_id_map:
                item_id = self.path_to_id_map[current_path]
                if self.tree.exists(item_id):
                    state = self.tree.set(item_id, "state")
                    if state == "checked": return True
                    if state == "unchecked": return False
            if current_path == self.source_dir:
                root_id = self.path_to_id_map.get(self.source_dir)
                return root_id and self.tree.exists(root_id) and self.tree.set(root_id, "state") != "unchecked"
            parent_path = os.path.dirname(current_path)
            if parent_path == current_path: return False
            current_path = parent_path

    def _generate_file_tree_string(self, full_tree=False):
        if not self.source_dir: return ""
        output_lines = [os.path.basename(self.source_dir) or self.source_dir]

        def recurse_tree(path, prefix):
            try:
                entries = sorted(os.listdir(path))
            except OSError:
                return
            for i, name in enumerate(entries):
                is_last = (i == len(entries) - 1);
                connector = "└─ " if is_last else "├─ ";
                child_path = os.path.join(path, name)

                if full_tree:
                    pass  # For the full tree, we don't apply any filters.
                else:
                    # For the selected tree, we must apply both filters.
                    if self._is_path_ignored(child_path): continue
                    if not self._is_path_selected(child_path): continue

                output_lines.append(f"{prefix}{connector}{name}")
                if os.path.isdir(child_path):
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    recurse_tree(child_path, new_prefix)

        recurse_tree(self.source_dir, "")
        return "\n".join(output_lines)

    def process_files(self):
        try:
            max_size = float(self.max_size_var.get()) * 1024 * 1024
            files_to_process = []
            self.after(0, self.update_status, "正在收集文件列表...")
            for dirpath, dirnames, filenames in os.walk(self.source_dir, topdown=True):
                # We still prune directories here for performance, using the central ignore logic
                dirnames[:] = [d for d in dirnames if not self._is_path_ignored(os.path.join(dirpath, d))]
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if not self._is_path_ignored(filepath) and self._is_path_selected(filepath):
                        files_to_process.append(filepath)
            with open(self.output_file, "w", encoding="utf-8") as outfile:
                if self.include_full_tree_var.get():
                    self.after(0, self.update_status, "正在生成完整文件结构树...")
                    full_tree_str = self._generate_file_tree_string(full_tree=True)
                    outfile.write("=" * 40 + " 完整项目结构 " + "=" * 40 + "\n\n")
                    outfile.write(full_tree_str)
                    outfile.write("\n\n" + "=" * 90 + "\n\n")
                self.after(0, self.update_status, "正在生成已选文件结构...")
                checked_tree_str = self._generate_file_tree_string(full_tree=False)
                outfile.write("=" * 40 + " 已选文件结构概览 " + "=" * 40 + "\n\n")
                outfile.write(checked_tree_str)
                outfile.write("\n\n" + "=" * 40 + " 文件内容详情 " + "=" * 40 + "\n\n")
                for i, filepath in enumerate(files_to_process):
                    self.after(0, self.update_status,
                               f"处理中 ({i + 1}/{len(files_to_process)}): {os.path.basename(filepath)}")
                    try:
                        if os.path.getsize(filepath) > max_size: continue
                    except OSError:
                        continue
                    if self._is_binary_file(filepath): continue
                    try:
                        with open(filepath, "rb") as f:
                            raw_data = f.read()
                        detected = chardet.detect(raw_data)
                        encoding = detected['encoding'] if detected and detected['confidence'] > 0.7 else 'utf-8'
                        content = raw_data.decode(encoding, errors='ignore')
                        relative_path = os.path.relpath(filepath, self.source_dir)
                        outfile.write(f"--- START OF FILE: {relative_path} ---\n\n")
                        outfile.write(content)
                        outfile.write(f'\n\n--- END OF FILE: {relative_path} ---\n\n')
                    except Exception:
                        logging.error(f"Error processing file {filepath}", exc_info=True)
            self.after(0, self.on_generation_complete, len(files_to_process))
        except Exception:
            logging.error("A critical error occurred in the process_files thread.", exc_info=True)
            self.after(0, lambda: messagebox.showerror("严重错误", "处理过程中发生严重错误，详情请查看日志文件。"))
            self.after(0, lambda: self.generate_button.config(state="normal"))

    def on_generation_complete(self, count):
        self.generate_button.config(state="normal")
        self.status_label.config(text=f"状态: 完成！共处理 {count} 个文件。")
        self._reveal_in_explorer(self.output_file)
        messagebox.showinfo("完成", f"成功聚合 {count} 个文件。\n\n已在文件夹中为您定位到输出文件！")

    def _is_binary_file(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                return b'\0' in f.read(1024)
        except Exception:
            return True


if __name__ == "__main__":
    app = ProjectDumperApp()
    app.mainloop()