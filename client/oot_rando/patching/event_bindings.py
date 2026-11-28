"""Complete native callback requirements when local subflows forward actors.

Inlining a native external flow keeps its entry-scoped actor arguments, but a
local call can reuse its caller's bound participant. That participant must
advertise every action/query required by the aliases forwarded to the callee.
Only declarations are extended: graph nodes, parameters and identities stay
unchanged, and every added method already belongs to a native callee actor.
"""


def complete_forwarded_actor_bindings(chart):
    """Union transitive local actor requirements without changing the graph.

    Entry arguments form intermediate nodes, including arguments forwarded by
    an entry that performs no actor action itself. Requirements propagate back
    through typed ``Argument`` and ``ActorIdentifier`` values to every alias
    and concrete participant. The finite fixed point handles shared tails and
    cycles and native entries sharing an action body whose actor names another
    entry's argument scope. External flows and undeclared world-actor literals retain their
    native binding behavior. Repeating the operation makes no further change.
    """
    from evfl.common import ActorIdentifier, Argument, StringHolder
    from evfl.event import SubFlowEvent, SubFlowSwitchEvent
    from .event_info import reachable

    entries = {}
    for entry in chart.entry_points:
        if entry.name in entries:
            raise ValueError("Actor forwarding has duplicate local entries.")
        entries[entry.name] = entry
    actors = list(chart.actors)
    by_identifier = {}
    requirements, edges = {}, set()
    unresolved_literals = set()

    def ensure(node):
        return requirements.setdefault(node, (set(), set()))

    def connect(source, destination):
        ensure(source)
        ensure(destination)
        edges.add((source, destination))

    for index, actor in enumerate(actors):
        by_identifier.setdefault(actor.identifier, []).append(index)
        node = ("actor", index)
        actions, queries = ensure(node)
        for collection, destination in ((actor.actions, actions), (actor.queries, queries)):
            for method in collection:
                if not isinstance(method.v, str) or not method.v:
                    raise ValueError("Actor forwarding has an invalid native method name.")
                destination.add(method.v)
        binding = actor.argument_entry_point.v
        if binding is not None:
            if entries.get(binding.name) is not binding or not actor.argument_name:
                raise ValueError("Actor forwarding has an invalid entry-scoped participant.")
            argument = ("argument", binding.name, actor.argument_name)
            # The argument and every alias for it need the same callback set.
            connect(node, argument)
            connect(argument, node)

    # Build all argument edges first. An intermediate entry can merely forward
    # an argument, so requirements cannot be inferred from actor rows alone.
    calls = []

    def referenced_actor(value):
        if isinstance(value, ActorIdentifier):
            yield value
        elif isinstance(value, dict):
            for nested in value.values():
                yield from referenced_actor(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                yield from referenced_actor(nested)

    def active_argument(owner, participant):
        indices = by_identifier.get(participant.identifier, ())
        if len(indices) != 1:
            raise ValueError("Actor forwarding has an ambiguous scoped participant: " + str(participant.identifier))
        if participant.argument_entry_point.v is not None:
            # Native entry points often share the same action nodes. The
            # resource actor can name an alternate entry's scope, although
            # this invocation receives the argument in the active entry.
            argument = ("argument", owner, participant.argument_name)
            node = ("actor", indices[0])
            connect(node, argument)

    for owner in entries.values():
        for event in reachable(owner.main_event.v):
            data = event.data
            participant = getattr(data, "actor", None)
            if participant is not None:
                active_argument(owner.name, participant.v)
            if getattr(data, "params", None) is not None:
                for identifier in referenced_actor(data.params.data):
                    matches = by_identifier.get(identifier, ())
                    if len(matches) > 1:
                        raise ValueError("Actor forwarding has an ambiguous scoped participant: " + str(identifier))
                    if matches:
                        active_argument(owner.name, actors[matches[0]])
            if (isinstance(data, (SubFlowEvent, SubFlowSwitchEvent))
                    and not data.res_flowchart_name and data.entry_point_name in entries):
                params = data.params.data if data.params is not None else {}
                calls.append((owner.name, data.entry_point_name, params))
    for owner, callee, params in calls:
        for parameter, value in params.items():
            source = ("argument", callee, parameter)
            if isinstance(value, ActorIdentifier):
                matches = by_identifier.get(value, ())
                if len(matches) > 1:
                    raise ValueError("Actor forwarding has an ambiguous concrete participant: " + str(value))
                if matches:
                    connect(source, ("actor", matches[0]))
                else:
                    # A native literal can refer directly to a world actor,
                    # without reusing any participant declared in this chart.
                    unresolved_literals.add(str(value))
            elif isinstance(value, Argument):
                destination = ("argument", owner, str(value))
                connect(source, destination)

    changed = True
    while changed:
        changed = False
        for source, destination in sorted(edges):
            for wanted, available in zip(requirements[source], requirements[destination]):
                missing = wanted - available
                if missing:
                    available.update(missing)
                    changed = True

    # All validation precedes mutation. Preserve original ordering and refs;
    # append only native requirements not already declared by the participant.
    updates = []
    for index, actor in enumerate(actors):
        added = []
        for collection, required in zip((actor.actions, actor.queries), requirements[("actor", index)]):
            missing = sorted(required - {method.v for method in collection})
            collection.extend(StringHolder(name) for name in missing)
            added.append(missing)
        if any(added):
            updates.append(dict(actor=str(actor.identifier), actions=added[0], queries=added[1]))
    return dict(actors=updates, actions=sum(len(row["actions"]) for row in updates),
                queries=sum(len(row["queries"]) for row in updates),
                forwarding_edges=len(edges), world_actor_literals=sorted(unresolved_literals))
