"""
Enrollment Code Model
=====================

Represents enrollment codes that administrators generate to allow
employees to register their devices with the ObserveX platform.

Security design:
- Codes are scoped to exactly one organization.
- Codes have an expiration timestamp.
- Codes can be single-use (max_uses=1) or limited-use.
- Codes can be revoked by admins at any time.
- Usage count is tracked and enforced server-side.
- An enrollment code is NOT a device credential — after enrollment,
  the device receives its own independent API key.
"""
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from server.models.base import Base


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    # max_uses=1 for single-use, max_uses=0 for unlimited (reusable)
    max_uses = Column(Integer, default=1)
    usage_count = Column(Integer, default=0)
    is_revoked = Column(Boolean, default=False)

    # Relationships
    organization = relationship("Organization", back_populates="enrollment_codes")
    created_by = relationship("User")

    @property
    def is_expired(self) -> bool:
        return datetime.datetime.utcnow() > self.expires_at

    @property
    def is_exhausted(self) -> bool:
        """True if the code has reached its maximum number of uses."""
        return self.max_uses > 0 and self.usage_count >= self.max_uses

    @property
    def is_usable(self) -> bool:
        """True if the code can still be used for enrollment."""
        return not self.is_revoked and not self.is_expired and not self.is_exhausted

    def __repr__(self):
        return f"<EnrollmentCode id={self.id} code={self.code!r} org={self.organization_id}>"
