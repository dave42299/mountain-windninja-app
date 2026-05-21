import { useNavigate } from "react-router";
import { MapPin } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <MapPin className="h-12 w-12 text-muted-foreground/40" />
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="text-sm text-muted-foreground">
        The page you're looking for doesn't exist or has been moved.
      </p>
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => navigate(-1)}>
          Go back
        </Button>
        <Button onClick={() => navigate("/")}>Return to map</Button>
      </div>
    </div>
  );
}
