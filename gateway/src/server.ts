import express from "express";

const app = express();
const port = Number(process.env.PORT ?? 8081);

app.use(express.json({ limit: "256kb" }));

app.get("/health", (_request, response) => {
  response.json({ status: "ok", service: "prama-dynamagh-gateway" });
});

app.listen(port, () => {
  console.log(`PRAMA-Dynamagh gateway listening on ${port}`);
});

