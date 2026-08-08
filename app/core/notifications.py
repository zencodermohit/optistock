from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class EmailService(ABC):
    """
    Abstract base class defining the contract for sending emails.
    In production, this interface guarantees we can swap SendGrid for AWS SES
    without touching ANY business logic in the routers or services.
    """

    @abstractmethod
    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        """Sends an email and returns True if successful."""
        pass


class MockEmailService(EmailService):
    """
    A mock implementation for local development and testing.
    Instead of actually sending an email (which costs money and requires API keys),
    it simply logs the email payload to the server console.
    """

    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        logger.info("========== MOCK EMAIL SENT ==========")
        logger.info(f"TO: {to_address}")
        logger.info(f"SUBJECT: {subject}")
        logger.info(f"BODY:\n{body}")
        logger.info("=====================================")
        return True


# Dependency Injection helper
def get_email_service() -> EmailService:
    """
    Returns the active email service implementation.
    If we ever buy a SendGrid API key, we literally just change this ONE line
    to return `SendGridEmailService()` instead of `MockEmailService()`.
    """
    return MockEmailService()
