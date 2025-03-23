# signals.py
import logging
from django.db import models, transaction
from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.conf import settings
from allauth.account.models import EmailAddress
from .models import CustomerProfile, TeamMemberProfile, PasswordHistory

logger = logging.getLogger(__name__)
User = get_user_model()

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Atomic profile creation with type validation"""
    if created:
        try:
            with transaction.atomic():
                # Verify final user type after full creation
                user = User.objects.get(pk=instance.pk)
                if user.type == User.Types.CUSTOMER:
                    CustomerProfile.objects.create(user=user)
                elif user.type == User.Types.TEAM_MEMBER:
                    TeamMemberProfile.objects.create(user=user)
                logger.info(f"Created {user.type} profile for {user.uuid}")
        except User.DoesNotExist:
            logger.error("User vanished before profile creation")
        except Exception as e:
            logger.error(f"Critical profile failure: {str(e)}")
            raise  # Preserve transaction integrity

@receiver(pre_save, sender=User)
def track_password_changes(sender, instance, **kwargs):
    """Atomic password history tracking with configurable limit"""
    if not instance.pk or instance._state.adding:
        return

    try:
        with transaction.atomic():
            original = User.objects.get(pk=instance.pk)
            if instance.password != original.password:
                # Record old password before change
                PasswordHistory.objects.create(
                    user=instance,
                    password=original.password
                )
                
                # Trim history using settings configuration
                max_history = getattr(settings, 'PASSWORD_HISTORY_LIMIT', 5)
                user_history = PasswordHistory.objects.filter(user=instance)
                
                # Calculate and remove excess entries
                if user_history.count() > max_history:
                    entries_to_remove = user_history.count() - max_history
                    old_entries = user_history.order_by('created_at')[:entries_to_remove]
                    PasswordHistory.objects.filter(pk__in=old_entries.values_list('id', flat=True)).delete()
                    
                logger.debug(f"Updated password history for {instance.uuid}")
    except User.DoesNotExist:
        logger.warning(f"Password tracking failed for {instance.uuid}")
    except Exception as e:
        logger.error(f"Password history update error: {str(e)}")
        raise

@receiver(pre_save, sender=User)
def normalize_user_identifiers(sender, instance, **kwargs):
    """Consistent identifier normalization"""
    if instance.email:
        instance.email = instance.email.strip().lower()
    if instance.username:
        instance.username = instance.username.strip().lower()
    
    # Sync allauth emails for existing users
    if instance.pk and EmailAddress.objects.filter(user=instance).exists():
        EmailAddress.objects.filter(user=instance).update(email=instance.email)

@receiver(post_save, sender=User)
def handle_soft_delete(sender, instance, created, **kwargs):
    """GDPR-compliant soft delete handling"""
    if not created and not instance.is_active:
        try:
            with transaction.atomic():
                # Anonymize core fields
                update_fields = []
                if instance.first_name != "Deleted":
                    instance.first_name = "Deleted"
                    update_fields.append('first_name')
                if instance.last_name != "User":
                    instance.last_name = "User"
                    update_fields.append('last_name')
                
                new_email = f"deleted_{instance.uuid}@example.invalid"
                if instance.email != new_email:
                    instance.email = new_email
                    update_fields.append('email')

                if update_fields:
                    instance.save(update_fields=update_fields)
                
                # Cleanup allauth associations
                EmailAddress.objects.filter(user=instance).delete()
                logger.info(f"Soft-deleted user {instance.uuid}")
                
        except Exception as e:
            logger.error(f"Soft delete handling failed for {instance.uuid}: {str(e)}")

@receiver(pre_delete, sender=User)
def handle_hard_delete(sender, instance, **kwargs):
    """Final cleanup for physical deletions"""
    try:
        EmailAddress.objects.filter(user=instance).delete()
        logger.info(f"Hard delete cleanup for {instance.uuid}")
    except Exception as e:
        logger.error(f"Hard delete cleanup failed for {instance.uuid}: {str(e)}")