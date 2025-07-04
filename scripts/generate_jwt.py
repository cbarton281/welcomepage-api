import jwt
import argparse
import datetime

"""
CLI utility to generate a JWT for testing Welcomepage API endpoints.
Requires the JWT secret to be provided on the command line.

Example usage:
    python generate_jwt.py --secret 'your-actual-secret' --user-id testuser --role ADMIN --seconds 600
"""

def main():
    parser = argparse.ArgumentParser(description="Generate a test JWT.")
    parser.add_argument("--secret", required=True, help="JWT secret key")
    parser.add_argument("--user-id", required=True, help="User ID (sub claim)")
    parser.add_argument("--role", required=True, choices=["USER", "ADMIN"], help="User role")
    parser.add_argument("--seconds", type=int, default=3600, help="Token expiry in seconds (default: 3600, i.e. 1 hour)")
    args = parser.parse_args()

    payload = {
        "sub": args.user_id,
        "role": args.role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=args.seconds)
    }

    token = jwt.encode(payload, args.secret, algorithm="HS256")
    print(token)

if __name__ == "__main__":
    main()
