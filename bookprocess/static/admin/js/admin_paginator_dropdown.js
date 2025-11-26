window.addEventListener('load', function() {
    (function($) {
        var paginator = $(".paginator");
        if (!paginator.length) return;

        if ($("#list_per_page_selector").length) return;

        var options = (window.list_per_page_options || "").split(",").map(Number);
        if (!options.length) return;

        var dropdown = $("<select id='list_per_page_selector' style='margin-left:8px;'></select>");
        options.forEach(function(n) {
            dropdown.append("<option value='" + n + "'>" + n + "</option>");
        });
        paginator.append(dropdown);

        var url = new URL(window.location.href);
        var current = parseInt(url.searchParams.get("list_per_page")) || options[0];
        dropdown.val(current);

        dropdown.on("change", function(e) {
            url.searchParams.set("list_per_page", e.target.value);
            url.searchParams.delete("page");
            window.location.href = url.href;
        });
    })(django.jQuery);
});
