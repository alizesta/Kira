# Domain and Application Boundary — Flow 2

**Target:** `new-main`  
**Work branch:** `architecture/domain-application-contracts`  
**Scope:** Pure Domain rules and values, application use cases, and Core-owned
cross-layer ports.  
**Coordination:** UI/controller internals remain owned by Flow 1. Bootstrap,
FeatureModule registration and legacy-wide cleanup remain coordinated with Flow 4.

## Implemented extractions

### Conversation lifecycle

- `kira/domain/conversations.py` owns durable Conversation statuses,
  lifecycle operations, transition errors/results and allowed source states.
- `kira/chat/conversation_lifecycle.py` remains the application coordinator:
  it reads through a repository port, validates Domain rules, commits using
  Persistence's atomic lifecycle operation, then publishes notifications.
- The existing module re-exports the old public names to preserve callers.

### Conversation organization

- `kira/domain/organization.py` owns organization metadata constants, filter
  and value contracts (`OrganizationFilter`, `Tag`, `Folder`), label/key
  normalization and bounded metadata validation.
- `kira/app/organization_application.py` owns the organization use cases:
  rename, tag, folder, favorite, metadata update and conversation filtering.
- `kira/core/interfaces/organization.py` defines atomic repository mutation
  and metadata-event publisher ports.
- `kira/chat/organization.py` is now a compatibility facade. Existing imports
  continue to resolve to the application service and Domain contracts.
- Corrected a pre-existing `add_tag` defect: the method referenced an
  undefined `folder` variable after its persistence write, causing a committed
  operation to raise before returning. The invalid reference was removed.

### Chat Search & Retrieval

- `kira/domain/search.py` owns immutable request/result/reference/page
  contracts, timestamp normalization, and snippet construction.
- `kira/app/chat_search_application.py` owns query validation, read paging,
  role/character/session/date/status filtering, matching, ranking and
  pagination.
- `kira/core/interfaces/search.py` defines a read-only message page port and
  an optional durable-Conversation status reader port. The Application use case
  accepts the status reader separately; it defaults to the repository only when
  that object implements the optional reader contract.
- `kira/chat/search.py` remains a compatibility facade.

### Chat Transfer

- `kira/domain/transfer.py` owns transfer schema/version constants, bounded
  import preview/result contracts, secret-key filtering and metadata validation.
- `kira/app/chat_transfer_application.py` owns export, preview, parsing,
  validation orchestration, safe atomic file output and import delegation.
- `kira/core/interfaces/transfer.py` defines the Persistence port for
  paginated export reads and atomic validated imports.
- `kira/chat/transfer.py` remains a compatibility facade.

### Chat Request and Response contracts

- `kira/domain/chat.py` owns immutable Chat request, response, provider-event,
  stream-event, status, application-event and ContextRequest/ContextResult values.
  Domain data types are shared snapshots, not live UI objects.
- `ChatRequest` and `SubmissionResult` are shared by the Domain and the FIFO
  Coordinator; the Coordinator's queue/admission behavior remains in
  `kira/chat/coordinator.py`.
- `ProviderEvent`, `ChatResponseResult`, `ResponseStreamEvent` and their
  enums are consumed by `ResponseHandler`; stream aggregation, terminal
  de-duplication and cleanup remain in `kira/chat/response_handler.py`.
- `ChatApplicationRequest`, `ChatApplicationEvent`, `RequestStatus`,
  `ApplicationEventKind`, `Submission` and `PersistenceOutcome` are consumed
  by `ChatApplicationService`, which remains the request orchestration owner
  in `kira/chat/application_service.py`.
- `kira/domain/chat.py` also owns ContextRequest/ContextResult; Core defines
  `SystemPromptBuilderPort` and `PromptEnricherPort`, while `ContextBuilder`
  keeps prompt assembly and context-window trimming as its existing algorithm.
- The old modules import/re-export these Domain values for compatibility.
  This extraction does not move or duplicate queueing, streaming state, prompt
  assembly or request lifecycle algorithms.

## Core application contracts

The following structural ports now live under `kira/core/interfaces`:

- `SessionManagerPort` and `RuntimeSessionPort`: runtime Session lifecycle
  and data required by Session orchestration.
- `ChatApplicationPort`: Conversation binding and pending-work queries.
- `ApplicationEventPublisherPort`: notification-only application event
  publication.
- `ConversationLifecycleRepositoryPort`,
  `ConversationEventPublisherPort` and
  `PermanentDeleteAuthorizationPort`.
- `ConversationOrganizationRepositoryPort` and
  `ConversationMetadataEventPublisherPort`.
- `ChatSearchRepositoryPort` and `ConversationStatusReaderPort`.
- `ChatTransferRepositoryPort`.

`SessionApplicationService` now depends on Core-owned structural ports rather
than untyped `Any` collaborators. The Conversation lifecycle, Organization,
Search and Transfer application services also consume Core-owned persistence
and notification ports. No new service imports Qt or a concrete UI controller.

## Dependency and ownership rules

- Domain imports only the standard library and other Domain modules.
- Core contracts do not import Application, Chat implementations, UI, Qt or
  Infrastructure implementations.
- Application services orchestrate Domain rules through narrow ports.
- Persistence remains the sole owner of durable records, database schema and
  transactions.
- Search is read-only; Transfer delegates durable writes to Persistence.
- Organization writes use the existing atomic Persistence mutation APIs and
  preserve unrelated metadata namespaces.
- Event publication is a notification after a successful durable commit; it
  is not a synchronous service locator.
- Compatibility facades stay until call sites and tests prove they can be
  removed safely.
- Flow 1 may change controllers and UI adapters, but must consume these public
  contracts rather than reaching into Domain or Persistence internals.
- Flow 4 owns central service registration, Bootstrap wiring and lifecycle
  integration. This branch does not edit Bootstrap, FeatureModule registration
  or controller/composition files.

## Verification added and wired

- `tests/test_domain_conversation_rules.py`: legal Conversation transition
  source states.
- `tests/test_domain_organization.py`: label normalization, metadata safety
  and organization value contracts.
- `tests/test_domain_search.py`: immutable Search DTOs, time bounds and
  snippet behavior.
- `tests/test_domain_transfer.py`: secret filtering and bounded metadata.
- `tests/test_domain_chat_contracts.py`: request/session identity pairing, immutable Chat/context DTOs, provider events and application/response event contracts.
- Existing `tests/test_chat_context_builder.py` continues to exercise context assembly through the compatibility import.
- `tests/test_application_service_ports.py`: Session, Chat and Event
  structural-port conformance.
- Existing `tests/test_chat_organization.py`, `tests/test_chat_search.py`
  and `tests/test_chat_transfer.py` continue to exercise the compatibility
  facades against the application use cases.
- `tests/test_architecture_boundaries.py` now requires an actual Domain
  package and checks Core/Domain dependency direction.
- Both Chat Session Lifecycle and portable release workflows include the new
  test modules; the lifecycle workflow also compiles the extracted source
  modules.

## Remaining Flow 2 work

The next bounded target is reviewing remaining broad collaborator annotations
in application services and defining ports only where a stable cross-layer
capability exists. Avoid inventing contracts for transient implementation
details merely to remove every `Any`.

Two explicit cross-flow follow-ups remain: Flow 3 should move path-based import
reads and atomic export-file writes behind an Infrastructure file port; Flow 4
must inject that adapter and register Organization/Search/Transfer use cases in
the central application lifecycle. Flow 2 has not claimed those integrations.

Central application-service registration, Bootstrap injection, FeatureModule
lifecycle and UI-controller consumption are coordinated through Flows 1 and 4,
not duplicated here.

## Verification boundary

Source and patch-level checks were performed through GitHub. Python tests,
`py_compile`, CI execution, Windows GUI acceptance and runtime startup/shutdown
have **not** been executed in this environment. No test pass or runtime
acceptance is claimed.
