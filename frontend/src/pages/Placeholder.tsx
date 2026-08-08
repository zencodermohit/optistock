import { Hammer } from "lucide-react";

import { PageHeader } from "@/components/layout/AppShell";
import { Band } from "@/components/ui/Band";
import { EmptyState } from "@/components/ui/states";

/**
 * A screen that is genuinely not built yet.
 *
 * Better than a dead link or a 404: it says what is coming and when. Being
 * honest about what is unfinished reads as deliberate; a nav item that leads
 * nowhere reads as broken.
 */
export function Placeholder({
  title,
  description,
  building,
}: {
  title: string;
  description: string;
  building: string;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Band>
        <EmptyState
          icon={<Hammer className="h-5 w-5" />}
          title="Not built yet"
          description={building}
        />
      </Band>
    </>
  );
}
