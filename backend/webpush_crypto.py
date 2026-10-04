"""The cryptography web push needs, in pure Python because the standard library has none of it: P-256 (ECDH and ECDSA), AES-128-GCM and
HKDF, and the encryption of a message for a browser (RFC 8291). Checked against known answers in tests/suites/push.py."""

import base64
import hashlib
import hmac
import re
import secrets


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64url_decode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]*', value):
        raise ValueError('not base64url')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


# -- P-256 --
# Points are kept as Jacobian (x, y, z) triples while they are worked on, which needs no division until the end; z == 0 is
# the point at infinity.
P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
P256_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
P256_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
P256_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
          0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)
EC_INFINITY = (1, 1, 0)


def ec_double(point):
    x, y, z = point
    if z == 0 or y == 0:
        return EC_INFINITY
    p = P256_P
    delta = z * z % p
    gamma = y * y % p
    beta = x * gamma % p
    alpha = 3 * (x - delta) * (x + delta) % p
    x3 = (alpha * alpha - 8 * beta) % p
    return x3, (alpha * (4 * beta - x3) - 8 * gamma * gamma) % p, ((y + z) ** 2 - gamma - delta) % p


def ec_add(first, second):
    if first[2] == 0:
        return second
    if second[2] == 0:
        return first
    p = P256_P
    x1, y1, z1 = first
    x2, y2, z2 = second
    z1z1, z2z2 = z1 * z1 % p, z2 * z2 % p
    u1, u2 = x1 * z2z2 % p, x2 * z1z1 % p
    s1, s2 = y1 * z2 * z2z2 % p, y2 * z1 * z1z1 % p
    if u1 == u2:
        return ec_double(first) if s1 == s2 else EC_INFINITY
    h, r = (u2 - u1) % p, (s2 - s1) % p
    h2 = h * h % p
    h3 = h * h2 % p
    v = u1 * h2 % p
    x3 = (r * r - h3 - 2 * v) % p
    return x3, (r * (v - x3) - s1 * h3) % p, h * z1 * z2 % p


def ec_multiply(scalar, point=P256_G):
    """scalar × point as an (x, y) pair, or None for the point at infinity. A Montgomery ladder: every bit does the same two
    operations, whichever it is."""
    base = (point[0], point[1], 1)
    low, high = EC_INFINITY, base
    for bit in bin(scalar % P256_N)[2:]:
        if bit == '1':
            low, high = ec_add(low, high), ec_double(high)
        else:
            high, low = ec_add(low, high), ec_double(low)
    if low[2] == 0:
        return None
    inverse = pow(low[2], -1, P256_P)
    return low[0] * inverse * inverse % P256_P, low[1] * inverse ** 3 % P256_P


def ec_on_curve(x, y):
    return 0 <= x < P256_P and 0 <= y < P256_P and (y * y - (x * x * x - 3 * x + P256_B)) % P256_P == 0


def encode_point(x, y):
    return b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')


def decode_point(raw):
    """The (x, y) of an uncompressed P-256 public key, which must be a point on the curve."""
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError('not an uncompressed P-256 point')
    x, y = int.from_bytes(raw[1:33], 'big'), int.from_bytes(raw[33:], 'big')
    if not ec_on_curve(x, y):
        raise ValueError('not on the curve')
    return x, y


def ecdsa_sign(private, message):
    """An ES256 signature (r then s, 32 bytes each) of the message."""
    z = int.from_bytes(hashlib.sha256(message).digest(), 'big')
    while True:
        k = secrets.randbelow(P256_N - 1) + 1
        r = ec_multiply(k)[0] % P256_N
        s = pow(k, -1, P256_N) * (z + r * private) % P256_N
        if r and s:
            return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


def hkdf(salt, key_material, info, length):
    """HKDF-SHA256 (RFC 5869): extract, then expand."""
    pseudo_random_key = hmac.new(salt, key_material, hashlib.sha256).digest()
    output = block = b''
    while len(output) < length:
        block = hmac.new(pseudo_random_key, block + info + bytes([len(output) // 32 + 1]), hashlib.sha256).digest()
        output += block
    return output[:length]


# -- AES-128 in GCM --
def aes_tables():
    """The S-box and the table that doubles a byte in GF(2^8), worked out rather than typed in."""
    sbox = [0] * 256
    rotated = lambda value, by: ((value << by) | (value >> (8 - by))) & 0xff
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xff) ^ (0x1b if p & 0x80 else 0)       # p times 3
        q ^= (q << 1) & 0xff                                         # q divided by 3
        q ^= (q << 2) & 0xff
        q ^= (q << 4) & 0xff
        if q & 0x80:
            q ^= 0x09
        sbox[p] = q ^ rotated(q, 1) ^ rotated(q, 2) ^ rotated(q, 3) ^ rotated(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox, [((value << 1) ^ (0x1b if value & 0x80 else 0)) & 0xff for value in range(256)]


AES_SBOX, AES_DOUBLE = aes_tables()


def aes_round_keys(key):
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for index in range(4, 44):
        word = words[index - 1][:]
        if index % 4 == 0:
            word = [AES_SBOX[byte] for byte in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = AES_DOUBLE[rcon]
        words.append([a ^ b for a, b in zip(words[index - 4], word)])
    return [sum(words[4 * round_number:4 * round_number + 4], []) for round_number in range(11)]


def aes_encrypt_block(round_keys, block):
    state = [a ^ b for a, b in zip(block, round_keys[0])]
    for round_number in range(1, 11):
        state = [AES_SBOX[byte] for byte in state]
        state = [state[(i + 4 * (i % 4)) % 16] for i in range(16)]       # shift rows
        if round_number < 10:
            mixed = []
            for column in range(0, 16, 4):
                a0, a1, a2, a3 = state[column:column + 4]
                mixed += [AES_DOUBLE[a0] ^ AES_DOUBLE[a1] ^ a1 ^ a2 ^ a3, a0 ^ AES_DOUBLE[a1] ^ AES_DOUBLE[a2] ^ a2 ^ a3,
                          a0 ^ a1 ^ AES_DOUBLE[a2] ^ AES_DOUBLE[a3] ^ a3, AES_DOUBLE[a0] ^ a0 ^ a1 ^ a2 ^ AES_DOUBLE[a3]]
            state = mixed
        state = [a ^ b for a, b in zip(state, round_keys[round_number])]
    return bytes(state)


def gcm_multiply(x, y):
    """Multiplication in GCM's field, on 128-bit integers."""
    z, v = 0, y
    for bit in range(127, -1, -1):
        if (x >> bit) & 1:
            z ^= v
        v = (v >> 1) ^ (0xe1 << 120) if v & 1 else v >> 1
    return z


def gcm_ghash(hash_key, data):
    value = 0
    for start in range(0, len(data), 16):
        value = gcm_multiply(value ^ int.from_bytes(data[start:start + 16].ljust(16, b'\0'), 'big'), hash_key)
    return value


def gcm_keystream_xor(round_keys, iv, data):
    """The data with the counter-mode keystream from block 2 of this IV (block 1 is for the tag) mixed in: encrypts or decrypts."""
    output = bytearray()
    for index in range(0, len(data), 16):
        counter = iv + (index // 16 + 2).to_bytes(4, 'big')
        output += bytes(a ^ b for a, b in zip(data[index:index + 16], aes_encrypt_block(round_keys, counter)))
    return bytes(output)


def gcm_tag(round_keys, iv, ciphertext):
    hash_key = int.from_bytes(aes_encrypt_block(round_keys, bytes(16)), 'big')
    lengths = (0).to_bytes(8, 'big') + (len(ciphertext) * 8).to_bytes(8, 'big')
    padded = ciphertext + bytes(-len(ciphertext) % 16)
    digest = gcm_ghash(hash_key, padded + lengths).to_bytes(16, 'big')
    return bytes(a ^ b for a, b in zip(digest, aes_encrypt_block(round_keys, iv + (1).to_bytes(4, 'big'))))


def aes_gcm_seal(key, iv, plaintext):
    """The ciphertext followed by its 16-byte tag, for a 16-byte key and a 12-byte IV, with nothing else authenticated."""
    round_keys = aes_round_keys(key)
    ciphertext = gcm_keystream_xor(round_keys, iv, plaintext)
    return ciphertext + gcm_tag(round_keys, iv, ciphertext)


# -- The message --
def encrypt_push_payload(payload, receiver_public, auth_secret, sender_private=None, salt=None):
    """`payload` encrypted for one browser (RFC 8291), as the body of the request to its push service: a header naming the
    salt and this message's own public key, then one record of aes128gcm (RFC 8188). The last two arguments are for tests,
    which need the same message twice; every real one has a key and salt of its own."""
    sender_private = sender_private or secrets.randbelow(P256_N - 1) + 1
    sender_public = encode_point(*ec_multiply(sender_private))
    shared = ec_multiply(sender_private, decode_point(receiver_public))
    if shared is None:
        raise ValueError('no shared secret')
    key_material = hkdf(auth_secret, shared[0].to_bytes(32, 'big'), b'WebPush: info\0' + receiver_public + sender_public, 32)
    salt = salt or secrets.token_bytes(16)
    key = hkdf(salt, key_material, b'Content-Encoding: aes128gcm\0', 16)
    nonce = hkdf(salt, key_material, b'Content-Encoding: nonce\0', 12)
    record = payload + b'\x02'
    if len(record) > 4096 - 16:
        raise ValueError('a push message is limited to about 4 KB')
    return salt + (4096).to_bytes(4, 'big') + bytes([len(sender_public)]) + sender_public + aes_gcm_seal(key, nonce, record)
