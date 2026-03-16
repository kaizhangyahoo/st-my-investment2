import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def lss(passcode) -> tuple[str, str] | tuple[None, None]:
    try:
        with open("t212.dat", "rb") as file:
            file_data = file.read()
        
        # The first 16 bytes are the salt, the rest is the encrypted message
        salt = file_data[:16]
        encrypted_data = file_data[16:]
        
        # Recreate the key using the SAME salt and passcode
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(passcode.encode()))
        f = Fernet(key)
        
        # Decrypt
        decrypted_data = f.decrypt(encrypted_data).decode()
        api_key, api_secret = decrypted_data.split("|")
        
        return api_key, api_secret

    except Exception as e:
        print("Error: Likely an incorrect passcode or corrupted file.")
        return None, None

if __name__ == "__main__":
    user_input = input("Enter your passcode to unlock API keys: ")
    key, secret = lss(user_input)

    if key:
        print(f"Success! API Key loaded: {key}")
        print(f"Success! API Secret loaded: {secret}")
