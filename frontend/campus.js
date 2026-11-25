const search = document.querySelector("#search");
const cards = document.querySelector("#cards");
const status = document.querySelector("#status");
const more = document.querySelector("#more");
const details = document.querySelector("#details");
const events = [];
const pageSize = 24;
let detailRequest;

async function getEventData(path, signal) {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error("Events unavailable");
  return response.json();
}

async function showDetails(event) {
  detailRequest?.abort();
  const controller = new AbortController();
  detailRequest = controller;
  const title = document.querySelector("#detail-title");
  const status = document.querySelector("#detail-status");
  const capacity = document.querySelector("#detail-capacity");
  title.textContent = event.title;
  status.textContent = "Loading event details…";
  capacity.textContent = "";
  details.showModal();
  try {
    const fresh = await getEventData(`/api/events/${encodeURIComponent(event.id)}`, controller.signal);
    if (controller.signal.aborted) return;
    title.textContent = fresh.title;
    status.textContent = fresh.status || "Status pending";
    capacity.textContent = fresh.capacity === null ? "Unlimited capacity" : `Capacity: ${fresh.capacity}`;
  } catch {
    if (!controller.signal.aborted) status.textContent = "Couldn’t load event details. Close and try again.";
  }
}

details.addEventListener("close", () => detailRequest?.abort());

function renderEvents() {
  const query = search.value.trim().toLowerCase();
  const filtered = events.filter((event) => event.title.toLowerCase().includes(query));
  cards.replaceChildren(...filtered.map((event) => {
    const card = document.createElement("article");
    const title = document.createElement("h3");
    title.textContent = event.title;
    const summary = document.createElement("p");
    summary.textContent = event.status || "Status pending";
    const button = document.createElement("button");
    button.textContent = "View event";
    button.setAttribute("aria-label", `View ${event.title}`);
    button.addEventListener("click", () => showDetails(event));
    card.append(title, summary, button);
    return card;
  }));
  status.textContent = filtered.length ? "" : "No matching events.";
}

async function loadEvents() {
  more.disabled = true;
  status.textContent = "Loading events…";
  try {
    const page = await getEventData(`/api/events?limit=${pageSize}&offset=${events.length}`);
    if (!Array.isArray(page)) throw new Error("Invalid event response");
    events.push(...page);
    search.disabled = false;
    renderEvents();
    more.hidden = page.length < pageSize;
    more.textContent = "Load more";
  } catch {
    status.textContent = "Couldn’t load events. Please try again.";
    more.hidden = false;
    more.textContent = "Retry";
  } finally {
    more.disabled = false;
  }
}
more.addEventListener("click", loadEvents);
search.addEventListener("input", renderEvents);
loadEvents();
