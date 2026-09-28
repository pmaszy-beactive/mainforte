import sgMail from "@sendgrid/mail";
import { logger } from "./logger";

const apiKey = process.env.SENDGRID_API_KEY;
const fromEmail = process.env.SENDGRID_FROM_USER;

if (apiKey) {
  sgMail.setApiKey(apiKey);
}

export async function sendPasswordResetEmail(
  toEmail: string,
  resetToken: string,
): Promise<void> {
  if (!apiKey || !fromEmail) {
    logger.warn("SendGrid not configured, skipping email send");
    return;
  }

  // Same SUBDOMAIN/PARENT_DOMAIN scheme as app.ts's CORS origin logic — see its comment for the
  // full rationale. Falls back to localhost so a local `npm run dev` (no SUBDOMAIN set) still
  // produces a usable, if non-clickable-in-prod, link during testing.
  const siteSubdomain = process.env.SUBDOMAIN;
  const parentDomain = process.env.PARENT_DOMAIN || "mainforte.ai";
  const domain = siteSubdomain ? `${siteSubdomain}.${parentDomain}` : "localhost";
  const protocol = domain.includes("localhost") ? "http" : "https";
  const resetUrl = `${protocol}://${domain}/reset-password?token=${resetToken}`;

  const msg = {
    to: toEmail,
    from: fromEmail,
    subject: "Reset Your Password - Hello World",
    text: `You requested a password reset. Click the link below to reset your password:\n\n${resetUrl}\n\nThis link will expire in 1 hour.\n\nIf you didn't request this, please ignore this email.`,
    html: `
      <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Reset Your Password</h2>
        <p>You requested a password reset. Click the button below to reset your password:</p>
        <p style="margin: 24px 0;">
          <a href="${resetUrl}" style="background-color: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">
            Reset Password
          </a>
        </p>
        <p style="color: #666; font-size: 14px;">This link will expire in 1 hour.</p>
        <p style="color: #666; font-size: 14px;">If you didn't request this, please ignore this email.</p>
      </div>
    `,
  };

  try {
    await sgMail.send(msg);
    logger.info({ to: toEmail }, "Password reset email sent");
  } catch (error) {
    logger.error({ error }, "Failed to send password reset email");
    throw new Error("Failed to send password reset email");
  }
}
