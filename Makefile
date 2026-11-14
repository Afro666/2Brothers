# The app version lives in VERSION (one line, major.minor.patch). deploy/update.sh passes it
# to the web image build; Settings > Developer shows it with the commit.
.PHONY: version bump
PART ?= patch

version:
	@echo "$$(head -n 1 VERSION) ($$(git log -1 --format=%h -- web VERSION))"

# make bump            -> 0.1.0 becomes 0.1.1
# make bump PART=minor -> 0.2.0;  PART=major -> 1.0.0
bump:
	@case "$(PART)" in major|minor|patch) ;; *) echo "PART must be major, minor or patch" >&2; exit 2;; esac
	@grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+' VERSION || { echo "VERSION is not major.minor.patch" >&2; exit 2; }
	@new=$$(awk -F. -v part=$(PART) 'NR==1 { if (part == "major") print $$1+1 ".0.0"; else if (part == "minor") print $$1 "." $$2+1 ".0"; else print $$1 "." $$2 "." $$3+1 }' VERSION) \
		&& echo "$$new" > VERSION && echo "VERSION is now $$new"
