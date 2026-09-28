import { Router, type IRouter } from "express";
import { getVersion } from "../lib/version";

const router: IRouter = Router();

router.get("/version", (_req, res) => {
  res.json(getVersion());
});

export default router;
