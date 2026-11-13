# Reject embedded foreign navigation before authentication

Fetch Metadata uses navigation mode for more than document links. The server
previously allowed every cross-site or same-site request whose mode was
`navigate`, so an iframe, object or embed could send repeated wrong guesses and
consume the local browser address's login allowance. The content response did
not need to be readable for the allowance to be consumed.

The existing browser guard now also checks the destination. Foreign navigation
is admitted only for a document destination or omitted legacy metadata. Other
foreign resource/navigation destinations are rejected before authentication.
Same-origin frames and ordinary non-browser clients retain their existing path.
The server already disallows framing its index; this makes admission consistent
with that boundary instead of allowing authentication side effects first.

Any URL-token request can submit a guessed password, including requests without
Fetch Metadata on plain HTTP LAN addresses. All headerless token attempts now
use one bounded query allowance. Header credentials use another allowance;
changing metadata cannot select a fresh query budget. Both retain real IPv6
subnet accounting and bounded overflow protection.

The two credential channels have independent counts and trust. A scripted
attacker can attempt both channels, so their combined budget is twice one
channel's configured budget. This bounded tradeoff keeps browser URL guesses
from locking out header-authenticated clients. Correct URL tokens refund the
query allowance; correct headers refund the header allowance. A recently
authenticated header client is not thereby exempt from query-channel subnet
pressure. Valid session cookies retain the existing authenticated path.

Repeated wrong links can block other URL-token links from the same address.
Each lockout expires, but an attacker who resumes guessing after each expiry
can sustain this denial; the address is forgotten after an idle period. A valid
shared link works when its query allowance is available. Requests without any
credential peek at both allowances and book no attempt. Transport tests cover
missing metadata and requests marked as prefetch without claiming real-browser
prefetch verification.

The [web.dev Fetch Metadata guide](https://web.dev/articles/fetch-metadata)
explains navigation/resource destinations and early rejection. This policy is
stricter than its example's iframe allowance, consistent with this app's existing
frame restrictions. Final responses declare all three Fetch Metadata fields in
`Vary`, preventing caches from reusing an allowed document response for a
rejected embedded request. Interim responses remain unchanged.

Loopback HTTP regressions verify rejection without consuming an authentication
attempt, followed by a valid login. Controls cover document links, omitted
legacy metadata and same-origin frames. Responses include Vary on both accepted
and rejected requests. These transport tests do not exercise a real browser.
They also cover foreign POST bodies on both API endpoints, unknown destinations,
header normalization, authentication-error Vary and the interim 100 response.
