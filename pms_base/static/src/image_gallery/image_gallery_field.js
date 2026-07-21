/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { ImageGallery } from "./image_gallery";

export class ImageGalleryField extends Component {
    static template = "pms_base.ImageGalleryField";

    static components = {
        ImageGallery,
    };

    static props = {
        ...standardFieldProps,
    };

    get galleryProps() {
        return {
            record: this.props.record,
            name: this.props.name,
            readonly: this.props.readonly,
        };
    }
}

export const imageGalleryField = {
    component: ImageGalleryField,
    supportedTypes: ["one2many"],
};

registry.category("fields").add("image_gallery_field", imageGalleryField);