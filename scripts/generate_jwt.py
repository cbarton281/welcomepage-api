import jwt
import argparse
import datetime

"""
CLI utility to generate a JWT for testing Welcomepage API endpoints.
Requires the JWT secret to be provided on the command line.

Example usage:
    python generate_jwt.py --secret 'your-actual-secret' --user-id testuser --role ADMIN --team-id team123 --seconds 600
"""

def main():
    parser = argparse.ArgumentParser(description="Generate a test JWT.")
    parser.add_argument("--secret", required=True, help="JWT secret key")
    parser.add_argument("--user-id", required=True, help="User ID (sub claim)")
    parser.add_argument("--role", required=True, choices=["USER", "ADMIN", "PRE_SIGNUP"], help="User role")
    parser.add_argument("--team-id", required=True, help="Team ID for access control")
    parser.add_argument("--seconds", type=int, default=3600, help="Token expiry in seconds (default: 3600, i.e. 1 hour)")
    args = parser.parse_args()

    payload = {
        "sub": args.user_id,
        "user_id": args.user_id,
        "role": args.role,
        "team_id": args.team_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=args.seconds)
    }
    print(payload)
    token = jwt.encode(payload, args.secret, algorithm="HS256")
    print("----------------------------------------------------------\n")
    print(token)

if __name__ == "__main__":
    main()
