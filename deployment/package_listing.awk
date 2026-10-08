# Accept legacy Accelerator-first and newer numeric-ID/Accelerator-last tables.
# mode=present succeeds only for an exact package name and type.
# mode=active prints the first active flat PL package name, or nothing.
{
    if ($1 ~ /^[0-9]+$/) {
        package_name = $NF
        package_type = $2
        package_slot = $(NF - 1)
    } else {
        package_name = $1
        package_type = $2
        package_slot = $NF
    }
    if (mode == "present" && package_name == name && package_type == type)
        found = 1
    if (mode == "active" && package_type ~ /^(PL_FLAT|XRT_FLAT)$/ &&
        package_slot ~ /^[0-9]+(->|,|$)/) {
        print package_name
        exit
    }
}
END {
    if (mode == "present")
        exit !found
}
