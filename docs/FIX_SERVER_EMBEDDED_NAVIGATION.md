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
