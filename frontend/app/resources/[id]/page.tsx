import { notFound } from "next/navigation";
import { MOCK_RESOURCES, getMockAlarmConfigs, getMockEvents } from "@/lib/mock-data";
import { ResourceDetailClient } from "@/components/resources/ResourceDetailClient";
import { ResourceEvents } from "@/components/resources/ResourceEvents";
import type { Metadata } from "next";

// When real backend API is ready, replace mock imports with:
// import { fetchResource, fetchAlarmConfigs } from "@/lib/api-functions";

interface ResourceDetailPageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: ResourceDetailPageProps): Promise<Metadata> {
  const { id } = await params;
  const decodedId = decodeURIComponent(id);
  const resource = MOCK_RESOURCES.find((r) => r.name === decodedId || r.id === decodedId);
  return {
    title: resource ? `${resource.name} | Alarm Manager` : "Resource Detail | Alarm Manager",
    description: resource
      ? `Alarm configuration for ${resource.name} (${resource.type})`
      : "Resource detail page",
  };
}

export default async function ResourceDetailPage({ params }: ResourceDetailPageProps) {
  const { id } = await params;
  const decodedId = decodeURIComponent(id);

  // Find resource by name or id
  const resource = MOCK_RESOURCES.find((r) => r.name === decodedId || r.id === decodedId);
  if (!resource) notFound();

  // Parallel data fetching (mock for now)
  // When real API is ready:
  //   const [resource, alarmConfigs, events] = await Promise.all([
  //     fetchResource(decodedId),
  //     fetchAlarmConfigs(decodedId),
  //     fetchEvents(decodedId),
  //   ]);
  const alarmConfigs = getMockAlarmConfigs(resource.id);
  const events = getMockEvents(resource.id);

  return (
    <div className="space-y-8">
      <ResourceDetailClient resource={resource} alarmConfigs={alarmConfigs} />

      {/* Bottom section */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <ResourceEvents events={events} />

        {/* Resource Health Map placeholder */}
        <div className="md:col-span-2 bg-gradient-to-br from-primary to-primary-container p-1 rounded-xl shadow-lg">
          <div className="bg-white h-full rounded-[10px] p-6 flex flex-col justify-between">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-headline font-bold text-lg mb-1">Resource Health Map</h3>
                <p className="text-sm text-slate-500">
                  Real-time status of associated dependencies
                </p>
              </div>
              <div className="bg-primary/5 px-3 py-1 rounded-full text-primary text-[10px] font-bold uppercase">
                Live View
              </div>
            </div>
            <div className="mt-4 flex gap-4 h-24 items-end">
              {[60, 90, 40, 55, 75, 30].map((h, i) => (
                <div
                  key={i}
                  className={`flex-1 rounded-t relative group transition-all duration-500 ${
                    h > 80 ? "bg-red-500/20" : "bg-green-500/20"
                  }`}
                  style={{ height: `${h}%` }}
                >
                  <div className="absolute -top-6 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 text-white px-2 py-1 rounded text-[10px] whitespace-nowrap z-10">
                    Node-{i + 1}: {h}%
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
