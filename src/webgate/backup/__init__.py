"""Full-state backup and restore.

Server credentials are stored encrypted with a key derived from ``settings.secret_key``,
so ciphertext is not portable between instances that do not share that key. A backup
therefore carries credentials *decrypted*, and restore re-encrypts them with the target
instance's own key. Because that makes the file a credential dump, credentials are only
included when the caller supplies a passphrase, and the payload is then encrypted with a
key derived from that passphrase.
"""
