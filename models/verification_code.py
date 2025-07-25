from sqlalchemy import Column, Integer, String, DateTime, Boolean, func
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class VerificationCode(Base):
    __tablename__ = "verification_codes"
    id = Column(Integer, primary_key=True)
    email = Column(String, index=True, nullable=False)
    code = Column(String(6), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    public_id = Column(String, index=True, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "code": self.code,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "used": self.used,
            "public_id": self.public_id,
        }