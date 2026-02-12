import base64
import string

_cccccccx = "testuser"
cccccccz = _cccccccx + string.ascii_letters[:1:-3] + string.hexdigits[6:12:2]

def decode(key, string):
    string = base64.urlsafe_b64decode(string + b'===')
    string = string.decode('latin')
    encoded_chars = []
    for i in range(len(string)):
        key_c = key[i % len(key)]
        encoded_c = chr((ord(string[i]) - ord(key_c) + 256) % 256)
        encoded_chars.append(encoded_c)
    encoded_string = ''.join(encoded_chars)
    return encoded_string

if __name__ == "__main__":
    scramble = b'ud--wr-4nbzKnr-5tIzCmZjBo6o'
    print(decode(cccccccz, scramble))