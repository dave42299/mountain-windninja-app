import { Ion } from "cesium";

const token = import.meta.env.VITE_CESIUM_ION_TOKEN as string | undefined;

if (!token || token === "paste-your-token-here" || token === "your-cesium-ion-token") {
  console.warn(
    "Cesium Ion token not configured. Set VITE_CESIUM_ION_TOKEN in frontend/.env\n" +
      "Get a free token at https://cesium.com/ion",
  );
} else {
  Ion.defaultAccessToken = token;
}
