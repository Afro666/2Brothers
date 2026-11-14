The prepared `menu-photo.png` is a typed menu with five names from the seeded
demo kitchen recipes. `make_menu_photo.ps1` regenerates it on Windows. It prints
the dates and covers explicitly. For a live check, upload it in the Planner with
the window **2026-11-16 through 2026-11-22** and delivery **2026-11-16**.

Expected names: Macaroni casserole, Chicken rice, Salmon soup, Meatballs potato,
Pasta cream chicken. All should match when the demo recipes have been seeded.
The engine sizes ingredients using those recipes and current stock. The upload
does not change the stored menu plan or approve/place the resulting proposal.

This image and the recorded-model unit tests are synthetic fixtures, not evidence
of a successful live Nemotron call. Live acceptance for #1136 requires an actual
upload, a waiting proposal in under 30 seconds, and measured latency/token usage
recorded in the issue after the shared endpoint is healthy.
