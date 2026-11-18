# Flow 3 — Chat Transfer filesystem adapter

## Ownership

The concrete implementation of Core's ChatTransferFilePort is:

- Module: kira/infrastructure/chat_transfer_file_adapter.py
- Class: LocalChatTransferFileAdapter
- Contract: kira/core/interfaces/transfer.py

The Infrastructure adapter owns operating-system file access only. It does not parse JSON, validate transfer schemas, access SQLite, or persist Chat records. ChatTransfer remains the Application use case and ChatPersistence remains the sole durable-record owner.

## Import read guarantees

read_bytes(source, max_bytes=...):

- Accepts only a regular file and rejects symbolic links, directories, devices, and other special files.
- Requires a non-negative integer size limit; booleans are not accepted as integers.
- Checks the file's recorded size before reading and rechecks the opened file.
- Reads no more than max_bytes + 1 bytes, so a file that grows after the metadata check cannot cause an unbounded allocation.
- Uses O_NOFOLLOW when the platform provides it and compares file identity around open.

## Export write guarantees

write_bytes_atomically(directory, filename, content):

- Requires an existing destination directory and a simple ASCII basename; path separators and traversal names are rejected.
- Creates a private temporary file in the destination directory, writes and flushes the full payload, then calls fsync.
- Uses os.replace to atomically replace the final path on the same filesystem.
- Synchronizes the containing directory where supported.
- Removes the temporary file on failure; an existing destination remains untouched if replacement fails.

The Application service already limits serialized exports to its transfer-file size cap and passes the complete bytes payload to this adapter.

## Composition

The adapter is injected through the existing ChatTransfer(..., file_port=...) contract. Bootstrap creates LocalChatTransferFileAdapter by default and passes it through run_application(transfer_file_port=...). Callers may still inject a different ChatTransferFilePort explicitly. The Application service's legacy standard-library fallback remains only for compatibility with direct callers that bypass the production Composition Root.

## Verification

The new focused test module is tests/test_chat_transfer_file_adapter.py. It covers bounded regular-file reads, oversized inputs, directory/symlink rejection, argument validation, safe filenames, atomic replacement, and cleanup/preservation when replacement fails.

The test module was executed in an isolated Python environment against the adapter source: 9 tests passed. This is focused component verification, not full-repository or Windows/GUI acceptance.
