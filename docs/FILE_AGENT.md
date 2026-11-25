# File Agent (T5-A)

Code: `kira/tools/fileagent.py`, registered in the Tool Registry under the `files` category. No new dependency is required.

## Tools

| Tool | Level | Function |
|---|---|---|
| `make_folder` | 2 (no confirmation) | Create a new folder |
| `create_file` | 2 | Create a text file with content (maximum 200 KB) |
| `append_text` | 2 | Append text to a plain-text file as a new paragraph on a new line |
| `copy_item` | 2 | Copy a file or folder (limit: 3,000 files / 500 MB; links and sensitive files are not copied) |
| `rename_item` | 2 | Rename an item in the same folder |
| `write_file` | 3 (confirmation) | Replace the entire content; a `.bak-<timestamp>` backup is created beside the file first |
| `delete_folder` | 3 | Move a folder to the Recycle Bin; known root folders such as Desktop/Documents are protected |
| `batch_files` | 3 | Copy/move/delete multiple items (maximum 50). If any destination conflicts by name, **nothing is performed** |
| `organise_folder` | 3 | Organize top-level files into subfolders by type (Images, Documents, etc.) or month |
| `undo_file_operation` | 3 | Undo the latest operation (up to 1 hour): create, copy, rename, move, append, write, organize, or batch operation |

Existing tools (`search_files`, `list_folder`, `file_info`, `read_file`, `delete_file`, `move_file`, `open_path`) remain unchanged.

## Safety rules (enforced in code, not only in the prompt)

- Every path passes through `PathPolicy`: only permitted folders are accessible; sensitive files (keys, passwords, `.env`, etc.) are excluded; Kira's own data, AppData, and Windows data are never accessible.
- **Nothing is silently overwritten.** Creating, copying, renaming, or moving onto an existing name produces an error.
- Level 2 tools run only when the **current user turn** explicitly requests a change (create, copy, rename, write, etc.). Text inside a file or web page cannot instruct Kira to write files.
- New files and names cannot use executable/script extensions (`exe`, `bat`, `ps1`, `lnk`, `js`, etc.). Names must satisfy Windows rules (reserved names such as CON, colon, trailing dot, and similar restrictions).
- After each operation, disk presence and size are checked; Kira reports the observed result.
- Reversible operations are recorded in `kira_file_ops.json` in the data directory.

## Limitations

- Deletion and undo for create/copy operations use the Windows Recycle Bin; this works only on Windows.
- These tools do not write Word/PDF files (T5-C).
- Organization affects only top-level files and does not modify subfolders.

## Windows 11 validation required

The original development handoff requested these runtime checks:

1. Create a folder with a Persian name under Documents (including OneDrive when Documents is redirected) and create a file inside it.
2. Delete a folder and undo a create/copy operation using the actual Recycle Bin.
3. Move between drives (`shutil.move`) and test long paths.
4. Test rename/write behavior when a file is open in another application and locked.
