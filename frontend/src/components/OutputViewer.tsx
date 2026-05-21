import { Download, File, FileText, Globe, Image, Settings } from "lucide-react";
import { useForecastOutput } from "@/hooks/use-forecasts";
import { getForecastOutputDownloadUrl } from "@/api/forecasts";
import type { ForecastStatus, OutputFileInfo } from "@/api/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface OutputViewerProps {
  forecastId: string;
  status: ForecastStatus;
}

const FILE_TYPE_INFO: Record<string, { label: string; icon: typeof File }> = {
  ".asc": { label: "Wind Grid", icon: FileText },
  ".prj": { label: "Projection", icon: FileText },
  ".cfg": { label: "Config", icon: Settings },
  ".json": { label: "Metadata", icon: FileText },
  ".tif": { label: "Raster", icon: Image },
  ".kmz": { label: "Google Earth", icon: Globe },
};

function getFileExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex) : "";
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / Math.pow(1024, exponent);
  return `${value.toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function getFileIcon(filename: string) {
  const ext = getFileExtension(filename);
  return FILE_TYPE_INFO[ext]?.icon ?? File;
}

function getFileTypeLabel(filename: string): string | null {
  const ext = getFileExtension(filename);
  return FILE_TYPE_INFO[ext]?.label ?? null;
}

export default function OutputViewer({
  forecastId,
  status,
}: OutputViewerProps) {
  const { data, isLoading, error } = useForecastOutput(forecastId, status);

  if (status !== "completed") {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Output Files</CardTitle>
          <CardDescription>
            Results will be available once the forecast completes
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Output Files</CardTitle>
          <CardDescription>Loading output files...</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Output Files</CardTitle>
          <CardDescription className="text-destructive">
            {error?.message ?? "Failed to load output files"}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const totalSize = data.files.reduce((sum, f) => sum + f.size_bytes, 0);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Output Files</CardTitle>
        <CardDescription>
          {data.files.length} file{data.files.length !== 1 ? "s" : ""} &middot;{" "}
          {formatBytes(totalSize)} total
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-left text-xs font-medium text-muted-foreground">
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2 text-right">Size</th>
                <th className="px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.files.map((file) => (
                <FileRow
                  key={file.filename}
                  file={file}
                  forecastId={forecastId}
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function FileRow({
  file,
  forecastId,
}: {
  file: OutputFileInfo;
  forecastId: string;
}) {
  const Icon = getFileIcon(file.filename);
  const typeLabel = getFileTypeLabel(file.filename);
  const downloadUrl = getForecastOutputDownloadUrl(forecastId, file.filename);

  return (
    <tr className="border-b last:border-0 hover:bg-accent/50">
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-mono text-xs">{file.filename}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {typeLabel ?? getFileExtension(file.filename) || "—"}
      </td>
      <td className="px-3 py-2 text-right text-xs text-muted-foreground">
        {formatBytes(file.size_bytes)}
      </td>
      <td className="px-3 py-2 text-right">
        <Button variant="ghost" size="sm" asChild className="h-7 gap-1 px-2">
          <a href={downloadUrl} download>
            <Download className="h-3.5 w-3.5" />
            <span className="text-xs">Download</span>
          </a>
        </Button>
      </td>
    </tr>
  );
}
