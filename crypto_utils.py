import base64
import struct
import os
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError

# Размеры полей на основании main.c в usign
PK_ALGO = b"Ed"
KEYID_SIZE = 8
PUBKEY_SIZE = 32
SECKEY_SIZE = 64  # seed (32) + pubkey (32)
SIG_SIZE = 64

# Структура секретного ключа (signify/usign):
# pkalg(2), kdfalg(2), kdfrounds(4), salt(16), checksum(8), fingerprint(8), seckey(64)
SECKEY_STRUCT = "<2s2sI16s8s8s64s"
# Структура публичного ключа: pkalg(2), fingerprint(8), pubkey(32)
PUBKEY_STRUCT = "<2s8s32s"
# Структура подписи: pkalg(2), fingerprint(8), sig(64)
SIG_STRUCT = "<2s8s64s"

def load_key(path):
    """
    Парсит signify-совместимые файлы ключей (.sec/.pub).
    Возвращает кортеж (fingerprint, key_data).
    Для .sec key_data - это 32-байтный seed.
    Для .pub key_data - это 32-байтный публичный ключ.
    """
    with open(path, 'r') as f:
        lines = f.readlines()
        if not lines or not lines[0].startswith("untrusted comment:"):
            raise ValueError("Неверный формат файла: отсутствует заголовок")
        
        b64_data = lines[1].strip()
        raw_data = base64.b64decode(b64_data)

        if len(raw_data) == struct.calcsize(SECKEY_STRUCT):
            # Секретный ключ
            pkalg, kdfalg, kdfrounds, salt, checksum, fingerprint, seckey = struct.unpack(SECKEY_STRUCT, raw_data)
            if pkalg != PK_ALGO:
                raise ValueError(f"Неподдерживаемый алгоритм: {pkalg}")
            # В usign seckey - это seed + pubkey. Нам нужен только seed (первые 32 байта)
            return fingerprint, seckey[:32]
        
        elif len(raw_data) == struct.calcsize(PUBKEY_STRUCT):
            # Публичный ключ
            pkalg, fingerprint, pubkey = struct.unpack(PUBKEY_STRUCT, raw_data)
            if pkalg != PK_ALGO:
                raise ValueError(f"Неподдерживаемый алгоритм: {pkalg}")
            return fingerprint, pubkey
        
        else:
            raise ValueError(f"Неверный размер данных ключа: {len(raw_data)} байт")

def sign_file(file_path, key_path, sig_path=None):
    """
    Создает файл .sig для указанного файла.
    """
    if sig_path is None:
        sig_path = file_path + ".sig"

    fingerprint, seed = load_key(key_path)
    
    with open(file_path, 'rb') as f:
        message = f.read()

    # PyNaCl использует детерминированную схему Ed25519 по умолчанию
    signing_key = SigningKey(seed)
    signature = signing_key.sign(message).signature

    # Формируем бинарную структуру подписи
    raw_sig = struct.pack(SIG_STRUCT, PK_ALGO, fingerprint, signature)
    b64_sig = base64.b64encode(raw_sig).decode('utf-8')

    with open(sig_path, 'w') as f:
        # В usign fingerprint в комментарии выводится как Big Endian uint64 в hex.
        # Так как fingerprint_u64() читает байты по порядку и сдвигает их в val, 
        # то data[0] - это MSB. Следовательно, .hex() от байтового массива даст нужную строку.
        fp_hex = fingerprint.hex()
        f.write(f"untrusted comment: signed by key {fp_hex}\n")
        f.write(b64_sig + "\n")

def verify_file(file_path, sig_path, pubkey_path):
    """
    Проверяет подпись файла.
    """
    # Загружаем публичный ключ
    fp_pub, pubkey = load_key(pubkey_path)
    
    # Загружаем подпись
    with open(sig_path, 'r') as f:
        lines = f.readlines()
        if len(lines) < 2:
            raise ValueError("Неверный формат файла подписи")
        b64_sig = lines[1].strip()
        raw_sig_data = base64.b64decode(b64_sig)
    
    if len(raw_sig_data) != struct.calcsize(SIG_STRUCT):
        raise ValueError("Неверный размер данных подписи")
    
    pkalg, fp_sig, signature = struct.unpack(SIG_STRUCT, raw_sig_data)
    
    if pkalg != PK_ALGO:
        raise ValueError(f"Неподдерживаемый алгоритм подписи: {pkalg}")
    
    # Проверка соответствия KeyID (fingerprint)
    if fp_pub != fp_sig:
        raise ValueError(f"ID ключа не совпадает: {fp_pub.hex()} != {fp_sig.hex()}")

    with open(file_path, 'rb') as f:
        message = f.read()

    verify_key = VerifyKey(pubkey)
    try:
        verify_key.verify(message, signature)
        return True
    except BadSignatureError:
        return False

def generate_keypair(key_basename, comment="OpenWrt Repo"):
    """
    Генерирует пару ключей Ed25519 в формате usign/signify.
    Создает файл с расширением .key (секретный) и .pub (публичный).
    """
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    
    seed = signing_key.encode() # 32 bytes
    pubkey = verify_key.encode() # 32 bytes
    
    # Fingerprint - это ID ключа, 8 байт.
    fingerprint = os.urandom(8)
    
    # 1. Публичный ключ
    raw_pub = struct.pack(PUBKEY_STRUCT, PK_ALGO, fingerprint, pubkey)
    b64_pub = base64.b64encode(raw_pub).decode('utf-8')
    with open(f"{key_basename}.pub", 'w') as f:
        f.write(f"untrusted comment: {comment} public key\n")
        f.write(b64_pub + "\n")
        
    # 2. Секретный ключ (без пароля)
    # seckey в usign - это seed + pubkey (64 байта)
    seckey_data = seed + pubkey
    # kdfalg=b"\x00\x00", kdfrounds=0, salt=0, checksum=0
    raw_sec = struct.pack(SECKEY_STRUCT, 
                          PK_ALGO, b"\x00\x00", 0, b"\x00"*16, b"\x00"*8, 
                          fingerprint, seckey_data)
    b64_sec = base64.b64encode(raw_sec).decode('utf-8')
    with open(f"{key_basename}.key", 'w') as f:
        f.write(f"untrusted comment: {comment} secret key\n")
        f.write(b64_sec + "\n")
    
    return fingerprint.hex()

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 crypto_utils.py <sign|verify> ...")
        sys.exit(1)
    
    cmd = sys.argv[1]
    try:
        if cmd == "sign" and len(sys.argv) >= 4:
            out_sig = sys.argv[4] if len(sys.argv) > 4 else None
            sign_file(sys.argv[2], sys.argv[3], out_sig)
            print(f"Файл {sys.argv[2]} успешно подписан.")
        elif cmd == "verify" and len(sys.argv) == 5:
            if verify_file(sys.argv[2], sys.argv[3], sys.argv[4]):
                print("OK")
            else:
                print("verification failed")
                sys.exit(1)
        elif cmd == "generate" and len(sys.argv) >= 3:
            name = sys.argv[2]
            comment = sys.argv[3] if len(sys.argv) > 3 else "OpenWrt Repo"
            fp = generate_keypair(name, comment)
            print(f"Ключи {name}.key и {name}.pub созданы. ID: {fp}")
        else:
            print("Неверные аргументы")
            print("Usage: python3 crypto_utils.py <sign|verify|generate> ...")
            sys.exit(1)
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)
