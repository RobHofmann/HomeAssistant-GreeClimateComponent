#!/usr/bin/env python3

import base64
import json
import sys
from Crypto.Cipher import AES

#key = b"r8Tu1Wx4Za7Cd0Fg"  # 
key = b"a3K8Bx%2r8Y7#xDh"  # default key (for scanning)
cipher = AES.new(key, AES.MODE_ECB)

def decrypt(ciphertext):
    return cipher.decrypt(base64.b64decode(ciphertext))

def parse(plaintext):
    plaintext = plaintext[:plaintext.rfind(b'}')+1].decode('utf-8')
    return json.loads(plaintext)

if __name__ == "__main__":
    print(parse(decrypt(sys.argv[1])))

