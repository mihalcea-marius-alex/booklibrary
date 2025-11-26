document.addEventListener("DOMContentLoaded", function () {
    'use strict';

    var $ = django.jQuery;

    function checkAuthorFields() {
        var $visibleRows = $('.dynamic-bookauthor_set:not(.empty-form)');
        var allRowsHaveAuthors = true;

        $visibleRows.each(function() {
            var $select = $(this).find('select[name*="author"]');
            var optionCount = $select.find('option').length;
            var selectVal = $select.val();

            if (optionCount === 0 || !selectVal) {
                allRowsHaveAuthors = false;
                return false;
            }
        });

        if (allRowsHaveAuthors) {
            $('tr.add-row').attr('style', 'display: table-row !important');
        } else {
            $('tr.add-row').attr('style', 'display: none !important');
        }
    }

    $('tr.add-row').hide();

    checkAuthorFields();

    $(document).on('change', 'select[name*="bookauthor_set"][name*="author"]', function() {
        checkAuthorFields();
    });

    $(document).on('click', '.inline-deletelink, tr.add-row a.addlink', function() {
        checkAuthorFields();
    });

    $(document).on('select2:select select2:unselect select2:clear', 'select[name*="bookauthor_set"][name*="author"]', function() {
        checkAuthorFields();
    });

    $('form').on('submit', function(e) {
        var $visibleRows = $('.dynamic-bookauthor_set:not(.empty-form)');

        $visibleRows.each(function() {
            var $row = $(this);
            var $select = $row.find('select[name*="author"]');
            var optionCount = $select.find('option').length;
            var selectVal = $select.val();

            if (optionCount === 0 || !selectVal) {
                var $deleteCheckbox = $row.find('input[name*="DELETE"]');
                if ($deleteCheckbox.length) {
                    $deleteCheckbox.prop('checked', true);
                } else {
                    $row.remove();
                }
            }
        });
    });
});
