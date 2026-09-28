import { logger } from "./logger";

/**
 * Replaces beactive-claw's site-status.ts (~575 lines: a persistent outbound WebSocket doing
 * heartbeats, chat-triggered rebuild command-and-control, and browser-console-error forwarding)
 * with a single one-shot POST once this process confirms it's listening. Mainforte has no
 * equivalent control-plane need: it pulls logs/files via its own container-agent path rather
 * than needing the container to push anything, and its own event/heartbeat model
 * (`Site.last_heartbeat`, the `site.*`/`build.*` event namespace) is driven by the Jenkins
 * pipeline step and mainforte's backend, not by this app. See PLAN.md's "Site starter template
 * fork" > "Replace the control plane" for the full rationale.
 *
 * CALLBACK_URL and CONTAINER_API_KEY are both Jenkins job params (see
 * sites/provisioning.py's trigger_provision), passed into this container's env at `docker run`
 * time. Note this is a lighter-weight "the app process is listening" signal -- the AUTHORITATIVE
 * "ready" callback (with container_name/dev_port, which this process cannot know about itself)
 * is sent by the Jenkins pipeline step once it confirms the container is up, not by this code.
 */
export async function notifyStarted(): Promise<void> {
  const callbackUrl = process.env.CALLBACK_URL;
  const apiKey = process.env.CONTAINER_API_KEY;
  if (!callbackUrl || !apiKey) {
    logger.warn("CALLBACK_URL/CONTAINER_API_KEY not set — skipping startup callback (local dev?)");
    return;
  }
  try {
    const res = await fetch(callbackUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ event: "log", line: "app process listening" }),
    });
    if (!res.ok) {
      logger.warn({ status: res.status }, "startup callback POST did not return 2xx");
    }
  } catch (err) {
    logger.warn({ err }, "startup callback POST failed");
  }
}
