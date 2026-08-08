from sqlalchemy.orm import Session
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditLogCreate


class AuditService:
    @staticmethod
    def log_action(db: Session, audit_data: AuditLogCreate) -> AuditLog:
        """
        Creates a new audit log entry for compliance tracking.
        """
        log_entry = AuditLog(**audit_data.model_dump())
        db.add(log_entry)
        db.flush()
        return log_entry
