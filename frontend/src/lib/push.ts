import { Capacitor } from "@capacitor/core";
import { PushNotifications } from "@capacitor/push-notifications";
import { api } from "./api";

let started = false;

/** Registers this device for push on native platforms only; no-op on web. */
export function startPushRegistration() {
  if (started) return;
  started = true;
  if (!Capacitor.isNativePlatform()) return;
  void register();
}

async function register() {
  const perm = await PushNotifications.checkPermissions();
  let status = perm.receive;
  if (status === "prompt" || status === "prompt-with-rationale") {
    status = (await PushNotifications.requestPermissions()).receive;
  }
  if (status !== "granted") return;

  PushNotifications.addListener("registration", (token) => {
    void api.push.register({ platform: Capacitor.getPlatform(), token: token.value });
  });
  PushNotifications.addListener("registrationError", (err) => {
    console.error("push registration failed", err);
  });

  await PushNotifications.register();
}
