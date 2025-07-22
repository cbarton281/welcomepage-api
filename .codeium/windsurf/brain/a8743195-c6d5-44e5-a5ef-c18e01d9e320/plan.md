# Welcomepage Onboarding & Auth Plan

## Overview
This plan tracks the steps and requirements to implement a robust onboarding and authentication flow for Welcomepage, including pre-signup object creation, email verification, and establishing a NextAuth session with a custom CredentialsProvider.

---

## Current Flow and Goals
1. **Pre-signup:**
   - User completes onboarding forms (team, profile) before signing up.
   - Data is persisted with a `public_id`, which is stored in a cookie.
2. **Email Verification:**
   - User enters email, which is saved to the profile and triggers a verification code email.
   - `public_id` is sent to backend and stored with the verification code.
3. **Code Entry:**
   - User enters the verification code in a modal dialog.
   - Code is verified via FastAPI backend.
4. **Session Establishment:**
   - On successful verification, a NextAuth CredentialsProvider is used to establish a session.
   - User is assigned a role (`admin` if team creator, `user` if invited, `pre-signup` before verification).

---

## Task List
- [x] Update backend to accept and store `public_id` with verification codes.
- [x] Update frontend to send `public_id` when requesting verification code.
- [x] Add tenacity retries to verification endpoints for DB reliability.
- [x] Connect email verification modal to FastAPI verification endpoint.
- [x] Create Next.js API route to proxy verification code check to FastAPI.
- [ ] Implement custom CredentialsProvider in NextAuth:
  - [ ] Accepts email and verification code.
  - [ ] Calls FastAPI to verify code and fetch user info (`public_id`, `role`).
  - [ ] On success, returns session including `public_id` and `role`.
- [ ] Update FastAPI to return `public_id` and `role` on verification.
- [ ] Update frontend to use NextAuth session after verification.
- [ ] Assign role (`admin` or `user`) after first successful verification.
- [ ] Update profile with email after code entry (if not already).
- [ ] Ensure proper session and role persistence across app.

---

## Next Step
Implement the custom CredentialsProvider in NextAuth to establish a session after successful code verification, using the FastAPI backend for verification and user info.
