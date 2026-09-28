import { useState, useEffect } from "react";

interface AppVersion {
  version: string;
}

export function useVersion() {
  const [version, setVersion] = useState<AppVersion | null>(null);

  useEffect(() => {
    const base = import.meta.env.BASE_URL.replace(/\/$/, "");
    fetch(`${base}/api/version`, { credentials: "include" })
      .then((res) => res.json())
      .then((data) => setVersion(data))
      .catch(() => {});
  }, []);

  return version;
}
