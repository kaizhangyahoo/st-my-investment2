import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import streamlit as st
from dotenv import load_dotenv


def generate_encrypted_file(passcode, api_key, api_secret):
    # 1. Generate a random salt (needed to safely derive a key from a password)
    salt = os.urandom(16)
    
    # 2. Set up the Key Derivation Function (KDF)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000, # High iterations make brute-force harder
    )
    
    # 3. Derive the key from your passcode
    key = base64.urlsafe_b64encode(kdf.derive(passcode.encode()))
    f = Fernet(key)
    
    # 4. Prepare data (storing as a simple string, but you could use json or pickle)
    secret_data = f"{api_key}|{api_secret}".encode()
    encrypted_data = f.encrypt(secret_data)
    
    # 5. Store the salt and the encrypted data together
    # We need the salt later to recreate the same key!
    with open("t212.dat", "wb") as file:
        file.write(salt + encrypted_data)
    print("Secrets encrypted and saved to a dat file")

if __name__ == "__main__":
    load_dotenv()
    k = st.secrets.get("api_keys", {}).get("trading212")
    v = os.getenv("secret")
    print(k, v)
    my_passcode = input("Create a master passcode: ")
    generate_encrypted_file(my_passcode, k, v)