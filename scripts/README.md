# JWT Generator Utility

This folder contains a CLI utility to generate JWT tokens for testing Welcomepage API endpoints that require authentication.

## Usage

Run the script with your desired parameters:

```
python generate_jwt.py --secret 'your-actual-secret' --user-id testuser --role ADMIN --seconds 600
```

- `--secret` (**required**): The JWT secret key (must match your API's `JWT_SECRET_KEY`)
- `--user-id` (**required**): The user ID to encode in the `sub` claim
- `--role` (**required**): The user role (`USER` or `ADMIN`)
- `--seconds` (optional): Token expiry in seconds (default: 3600, i.e. 1 hour)

## Security Notes
- **Never** expose your real secret in public repositories or logs.
- This script is for local development and testing only.
- Do **not** expose this script as an API endpoint or include it in production deployments.

---

Example output can be pasted into the FastAPI docs "Authorize" dialog as:

```
Bearer <your-jwt-here>
```
