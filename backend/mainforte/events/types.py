"""Event taxonomy v1. Every surface ships with its events on day one, even if every handler is a no-op.

Naming: dot-namespaced, past tense for facts, `*.requested` for commands.
"""
from __future__ import annotations

EVENT_TYPES: dict[str, str] = {
    # connection
    "connection.opened": "A client or worker socket connected",
    "connection.closed": "A client or worker socket disconnected",
    "connection.resumed": "A socket reconnected and replayed from a last-seen id",
    # session / user
    "session.login": "User logged in",
    "session.logout": "User logged out",
    "session.impersonation.started": "Superuser started impersonating a user",
    "session.impersonation.ended": "Superuser stopped impersonating",
    "user.created": "User account created",
    "user.updated": "User profile updated",
    "user.password.reset_requested": "Password reset email requested",
    "user.password.reset": "Password was reset",
    # workspace
    "workspace.created": "Workspace created",
    "workspace.member.added": "Member added to workspace",
    "workspace.member.removed": "Member removed from workspace",
    "workspace.plan.changed": "Workspace plan changed",
    # billing
    "billing.card.saved": "Payment method saved",
    "billing.subscription.created": "Subscription created",
    "billing.subscription.renewed": "Subscription renewed",
    "billing.subscription.past_due": "Subscription past due",
    "billing.subscription.canceled": "Subscription canceled",
    "billing.reconcile.ran": "Stripe reconcile job ran",
    "billing.usage.recorded": "Usage recorded against a workspace",
    # chat
    "chat.message.created": "A human posted a message",
    "chat.message.feedback": "Human gave feedback on a message (not important / thumbs)",
    "chat.thread.created": "Thread created",
    "chat.thread.rolled_up": "Thread rolled up into a summary",
    "chat.attachment.uploaded": "A file was attached",
    # persona
    "persona.invited": "Persona added to workspace",
    "persona.renamed": "Persona renamed",
    "persona.removed": "Persona removed",
    "persona.reply.started": "Persona started replying",
    "persona.reply.delta": "Streaming chunk of a persona reply",
    "persona.reply.ended": "Persona finished replying",
    "persona.reply.error": "Persona reply failed",
    "persona.help.requested": "Persona asked another persona for help",
    "persona.reply.cancel_requested": "Human asked a persona to stop replying",
    "persona.reply.canceled": "Persona reply was canceled",
    # memory
    "memory.noted": "A note was added to workspace or persona memory",
    # governor
    "governor.claim.extracted": "Governor pulled a checkable claim from a reply",
    "governor.claim.verified": "Governor confirmed a claim against real events or memory",
    "governor.claim.unverified": "Governor found no evidence for a claim",
    "governor.claim.contradicted": "Governor found a claim conflicts with memory or thread history",
    "governor.reply.held": "Governor held a reply pending correction (unverified action claim)",
    "governor.reply.released": "Governor released a reply to the client (optionally flagged)",
    "governor.reply.corrected": "Persona was re-prompted and corrected after a held reply",
    # task
    "task.planned": "Plan drafted",
    "task.approval.requested": "Plan awaits user approval",
    "task.approved": "User approved plan",
    "task.rejected": "User rejected plan",
    "task.stage.started": "Stage started",
    "task.stage.ended": "Stage ended",
    "task.blocked": "Task needs a human (2FA, purchase, captcha)",
    "task.input.received": "Human provided the blocked input",
    "task.qa.passed": "QA passed",
    "task.qa.failed": "QA failed",
    "task.completed": "Task completed",
    "task.failed": "Task failed",
    "task.cancel.requested": "Human asked to cancel a task",
    "task.canceled": "Task canceled",
    "task.resumed": "Task resumed after interruption (redeploy, worker loss)",
    "task.scheduled": "Task scheduled for recurrence",
    "task.disabled": "Recurring task disabled",
    # agent work
    "agent.work.queued": "Work job queued",
    "agent.work.started": "Worker picked up job",
    "agent.work.progress": "Progress update",
    "agent.work.screenshot": "Screenshot attached",
    "agent.work.error": "Work job errored",
    "agent.work.ended": "Work job ended",
    # tool
    "tool.started": "Tool call started",
    "tool.progress": "Tool progress",
    "tool.ended": "Tool call ended",
    "tool.error": "Tool call failed",
    "tool.approval.requested": "Tool needs approval",
    "tool.approval.granted": "Tool approval granted",
    # browser
    "browser.session.opened": "Browser session opened",
    "browser.session.closed": "Browser session closed",
    "browser.navigation": "Browser navigated",
    "browser.handoff.requested": "Browser needs the human (2FA/captcha)",
    "browser.handoff.completed": "Human handed the browser back",
    # build
    "build.started": "Build started",
    "build.log": "Build log line",
    "build.succeeded": "Build succeeded",
    "build.failed": "Build failed",
    # widget
    "widget.created": "Widget created",
    "widget.updated": "Widget updated",
    "widget.published": "Widget published",
    "widget.viewed": "Widget viewed",
    "widget.disabled": "Widget disabled",
    # worker
    "worker.online": "Agent worker online",
    "worker.offline": "Agent worker offline",
    "worker.job.picked": "Worker picked a job",
    "worker.job.released": "Worker released a job",
    "worker.home.staged": "Worker staged a user home from S3",
    "worker.home.synced": "Worker synced a user home to S3",
    # system
    "system.error": "Unhandled error",
    "system.outbox.redispatched": "Outbox sweeper re-dispatched undelivered events",
}


def is_known(event_type: str) -> bool:
    return event_type in EVENT_TYPES
